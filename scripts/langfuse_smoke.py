"""本机 self-hosted Langfuse smoke：一条独立测试 run 的写入 → 读回 → 血缘核对。

用法（在已配置 `LANGFUSE_BASE_URL` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`
的 shell 里，且本机 Langfuse v4 正在运行）：

    .venv/Scripts/python.exe scripts/langfuse_smoke.py

红线：只连 `LANGFUSE_BASE_URL`（脚本会校验必须是 localhost）；
不启动 Harness / PyBoy / ROM / 真实模型；不打印任何密钥。
总超时 60 秒，到期明确报告 eventual consistency 未验证，不无限等待。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pokemon_agent.env import load_env_file
from pokemon_agent.trace import LangfuseTrace
from pokemon_agent.trace.langfuse_support import build_client_from_environment, read_observations

POLL_DEADLINE_SECONDS = 60.0
POLL_INTERVAL_SECONDS = 2.0
# 故意的固定等待：flush 只保证进了 SDK 批量导出队列，OTEL span 落库另有延迟；
# 先睡一拍再开始核对，避免把 eventual consistency 的抖动算成缺陷。
SETTLE_WAIT_SECONDS = 5.0

# 期望的封套事件（带 pokemon_trace envelope、能被 read_events 还原的账）：
#   main 线 7 笔 + restore 线 9 笔（完整后续）+ main 的 run_end 1 笔 = 17 笔。
# scope observation（branch ×2、伪造 run_start (fake)、episode/task/step）不带封套，不计入。
MAIN_EVENTS = [
    "run_start",
    "episode_start",
    "task_start",
    "sense_frame",
    "press_key",
    "choose_call",
    "checkpoint_save",
]
RESTORE_EVENTS = [
    "checkpoint_restore",
    "episode_start",
    "task_start",
    "sense_frame",
    "press_key",
    "choose_call",
    "task_end",
    "episode_end",
    "run_end",
]
EXPECTED_TOTAL = len(MAIN_EVENTS) + len(RESTORE_EVENTS) + 1  # + main 线 run_end

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def _meta(
    episode_id: str = "ep-1",
    task_id: str = "task-1",
    step: int = 0,
    branch: str = "main",
    **extra: object,
) -> dict[str, Any]:
    """meta 由调用方盖好 run_id / branch（0927 定案：trace 后端零持有）。

    缺省按 task 层账形状（task 位真 task 号）；episode 层账显式传 `task_id=""`
    （0928 定稿：episode 层账 task 位清空）。
    """
    return {
        "source": "smoke",
        "run_id": run_id,
        "branch": branch,
        "episode_id": episode_id,
        "task_id": task_id,
        "step": step,
        **extra,
    }


def _row_meta(row: object) -> dict[str, Any]:
    """observation 的 metadata（v2 API 回 dict；异常形状给空）。"""
    value = getattr(row, "metadata", None)
    return value if isinstance(value, dict) else {}


def _event_meta(row: object) -> dict[str, Any]:
    """observation metadata 里嵌的那份账 meta。"""
    value = _row_meta(row).get("event_meta")
    return value if isinstance(value, dict) else {}


# ========== 0. 前置校验 ==========

load_env_file(Path(__file__).resolve().parent.parent / ".env")

missing = [
    k
    for k in ("LANGFUSE_BASE_URL", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
    if not os.getenv(k)
]
check("环境变量三件齐全", not missing, "缺: " + ",".join(missing) if missing else "")
if missing:
    sys.exit(2)
print("配置来源: .env 与 shell 环境变量（.env 优先级低，shell 已设的不覆盖）")

base_url = os.environ["LANGFUSE_BASE_URL"]
host = base_url.split("//", 1)[-1].split(":", 1)[0].split("/", 1)[0]
local_ok = host in ("localhost", "127.0.0.1", "0.0.0.0", "::1")
check("BASE_URL 指向本机", local_ok, base_url if local_ok else "非本机地址，红线拒绝")
if not local_ok:
    sys.exit(2)

try:
    with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/public/health", timeout=5) as resp:
        health = json.loads(resp.read())
    version = health.get("version") or health.get("versions") or "?"
    check("Langfuse 健康检查", True, f"version={version}")
except Exception as exc:  # noqa: BLE001
    check("Langfuse 健康检查", False, f"{type(exc).__name__}: {exc}")
    sys.exit(2)

# ========== 1. 准备：客户端、tracelog 快照 ==========

client = build_client_from_environment()
suffix = uuid.uuid4().hex[:6]
run_id = f"handoff-{suffix}"
restore_branch = f"restore-{suffix}"
checkpoint_id = f"cp-{suffix}"
tracelog = Path("tracelog")
before = (
    {p: p.stat().st_mtime for p in tracelog.rglob("*") if p.is_file()} if tracelog.exists() else {}
)
print(f"\nrun_id={run_id}  (分支: main → {restore_branch}, checkpoint: {checkpoint_id})\n")

# ========== 2. 写入：main 线 ==========

trace_id = client.create_trace_id(seed=run_id)
main = LangfuseTrace(trace_id=trace_id, client=client)
main.append("lifecycle", "run_start", _meta(episode_id="", task_id=""), {"smoke": True})
main.append("lifecycle", "episode_start", _meta(task_id=""), {"map_id": 12})
main.append("lifecycle", "task_start", _meta(), {"goal": "smoke synthetic goal"})
main.append("view", "sense_frame", _meta(step=1), {"frame": "synthetic"})
main.append("act", "press_key", _meta(step=1), {"key": "a"})
main.append(
    "model_call",
    "choose_call",
    _meta(step=1),
    {"model": "smoke-synthetic", "input_tokens": 10, "output_tokens": 2, "prompt": "synthetic"},
)
main.append(
    "lifecycle",
    "checkpoint_save",
    _meta(task_id="", step=6, checkpoint_id=checkpoint_id),
    {"level": "episode"},
)
main.flush()
print("main 线 7 笔已写、flush 完成")

# ========== 3. 等 save 可见（记录延迟），建 restore 线（episode 级恢复） ==========

wait_start = time.monotonic()
save_visible = False
while time.monotonic() - wait_start < POLL_DEADLINE_SECONDS:
    rows = read_observations(client, trace_id)
    if any(_event_meta(o).get("checkpoint_id") == checkpoint_id for o in rows):
        save_visible = True
        break
    time.sleep(POLL_INTERVAL_SECONDS)
save_wait = time.monotonic() - wait_start
check(
    "checkpoint_save 经 API 可读（eventual consistency）",
    save_visible,
    f"等待 {save_wait:.1f}s" if save_visible else f"{POLL_DEADLINE_SECONDS}s 内不可见",
)

child = LangfuseTrace(trace_id=trace_id, client=client)  # 同 seed 同 trace：恢复线住同一条 trace
child.append(
    "lifecycle",
    "checkpoint_restore",
    _meta(task_id="", step=6, branch=restore_branch, checkpoint_id=checkpoint_id),
    {"level": "episode", "manifest_path": f"checkpoints/{checkpoint_id}/manifest.json"},
)
child.append(
    "lifecycle",
    "episode_start",
    _meta(episode_id="ep-2", task_id="", branch=restore_branch),
    {"restored": True},
)
child.append(
    "lifecycle",
    "task_start",
    _meta(episode_id="ep-2", task_id="task-2", branch=restore_branch),
    {},
)
child.append(
    "view",
    "sense_frame",
    _meta(episode_id="ep-2", task_id="task-2", step=1, branch=restore_branch),
    {},
)
child.append(
    "act",
    "press_key",
    _meta(episode_id="ep-2", task_id="task-2", step=1, branch=restore_branch),
    {"key": "a"},
)
child.append(
    "model_call",
    "choose_call",
    _meta(episode_id="ep-2", task_id="task-2", step=1, branch=restore_branch),
    {"model": "smoke-synthetic", "input_tokens": 4, "output_tokens": 1, "prompt": "synthetic"},
)
child.append(
    "lifecycle",
    "task_end",
    _meta(episode_id="ep-2", task_id="task-2", branch=restore_branch),
    {},
)
child.append(
    "lifecycle",
    "episode_end",
    _meta(episode_id="ep-2", task_id="", branch=restore_branch),
    {},
)
child.append("lifecycle", "run_end", _meta(episode_id="", task_id="", branch=restore_branch), {})
child.flush()  # 不 flush 的话 span 还在 SDK 队列里，下面的 API 树形核对会查空
print(f"故意等待 {SETTLE_WAIT_SECONDS:.0f}s（等 OTEL 批量导出落地）…")
time.sleep(SETTLE_WAIT_SECONDS)


def _obs_by(pred: Callable[[object], bool]) -> list[object]:
    return [o for o in read_observations(client, trace_id) if pred(o)]


def _top_level(obs: object, row_ids: set[str]) -> bool:
    """顶层 = 父不在本 trace 行集。

    SDK 对无 parent 的 start_observation 会造一个随机 remote parent id 并标
    AS_ROOT（`_create_remote_parent_span`），UI 按无父渲染——所以不能直接判
    parent_observation_id 为空，要看那个父是不是本 trace 里真实存在的账。
    """
    parent = getattr(obs, "parent_observation_id", None)
    return not parent or parent not in row_ids


# scope span 可能仍在上报/可见性延迟里，限时轮询到伪造锚出现
wait_start = time.monotonic()
fakes: list[object] = []
while time.monotonic() - wait_start < POLL_DEADLINE_SECONDS:
    fakes = [o for o in read_observations(client, trace_id) if _row_meta(o).get("synthetic")]
    if len(fakes) >= 1:
        break
    time.sleep(POLL_INTERVAL_SECONDS)

# ---- 树形核对（0927 定稿形状）----

rows = read_observations(client, trace_id)
row_ids = {getattr(o, "id", "") for o in rows}

branch_main = _obs_by(lambda o: getattr(o, "name", "") == "branch:main")
check(
    "main 线 branch scope 恰一个、顶层无父",
    len(branch_main) == 1 and _top_level(branch_main[0], row_ids),
)

branch_child = _obs_by(lambda o: getattr(o, "name", "") == f"branch:{restore_branch}")
check(
    "restore branch scope 顶层成根（不再挂 checkpoint_save、无空壳 run root）",
    len(branch_child) == 1
    and _top_level(branch_child[0], row_ids)
    and _row_meta(branch_child[0]).get("parent_checkpoint_id") == checkpoint_id,
)

fake_runs = [o for o in fakes if getattr(o, "name", "") == "run_start (fake)"]
check(
    "伪造 run_start 锚恰一个，挂 restore branch 下、带 synthetic",
    len(fake_runs) == 1
    and bool(branch_child)
    and getattr(fake_runs[0], "parent_observation_id", None) == branch_child[0].id,
)

run_starts = _obs_by(
    lambda o: getattr(o, "name", "") == "run_start" and not _row_meta(o).get("synthetic")
)
main_run = next(
    (o for o in run_starts if _row_meta(o).get("event_meta", {}).get("branch") == "main"), None
)
child_run_end = _obs_by(
    lambda o: (
        getattr(o, "name", "") == "run_end"
        and _row_meta(o).get("event_meta", {}).get("branch") == restore_branch
    )
)
main_episode_under_run = bool(main_run) and any(
    getattr(o, "name", "") == "episode_start"
    and getattr(o, "parent_observation_id", None) == main_run.id
    and _event_meta(o).get("episode_id") == "ep-1"
    for o in rows
)
check("main 树：episode_start 挂真 run_start 下", main_episode_under_run)
check(
    "restore 树：run_end 挂伪造 run_start 下（伪造锚顶替 run 层锚）",
    fake_runs
    and child_run_end
    and getattr(child_run_end[0], "parent_observation_id", None) == fake_runs[0].id,
)
check(
    "restore 树：checkpoint_restore 与真 episode_start 都挂伪造 run_start 下",
    fake_runs
    and all(
        getattr(o, "parent_observation_id", None) == fake_runs[0].id
        for o in _obs_by(
            lambda o: (
                getattr(o, "name", "") in {"checkpoint_restore", "episode_start"}
                and _row_meta(o).get("event_meta", {}).get("branch") == restore_branch
            )
        )
    ),
)

child_episode_start = next(
    (
        o
        for o in _obs_by(
            lambda o: (
                getattr(o, "name", "") == "episode_start"
                and _event_meta(o).get("episode_id") == "ep-2"
            )
        )
    ),
    None,
)
child_task_start = next(
    (o for o in _obs_by(lambda o: getattr(o, "name", "") == "task_start")), None
)
check(
    "restore 树：续跑 task_start 挂真 episode_start (ep-2) 下",
    bool(child_episode_start)
    and bool(child_task_start)
    and getattr(child_task_start, "parent_observation_id", None) == child_episode_start.id,
)


def _envelope_ended_at(obs: object) -> float:
    """observation 侧读封套 `ended_at`（双时刻定案：排序核对以封套为准）。"""
    output = getattr(obs, "output", None)
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except json.JSONDecodeError:
            return 0.0
    envelope = output.get("pokemon_trace", {}) if isinstance(output, dict) else {}
    value = envelope.get("ended_at", 0.0) if isinstance(envelope, dict) else 0.0
    return float(value)


restore_rows = [
    o
    for o in rows
    if _event_meta(o).get("branch") == restore_branch
    and isinstance(_row_meta(o).get("event_meta"), dict)
]

check(
    "restore 树：run_end 是恢复线最晚的封套 ended_at（双时刻定案后排序以封套为准）",
    bool(child_run_end)
    and bool(restore_rows)
    and _envelope_ended_at(child_run_end[0]) == max(_envelope_ended_at(o) for o in restore_rows),
    "ended_at 序: "
    + " ".join(
        f"{_row_meta(o).get('event_kind')}={_envelope_ended_at(o):.3f}" for o in restore_rows
    ),
)

raw_inputs = [
    getattr(o, "input", None)
    for o in rows
    if _row_meta(o).get("event_kind") == "choose_call" and not _row_meta(o).get("synthetic")
]
# v2 API 的 io 字段回程是 JSON 字符串（写入侧是对象），读侧要过一道 json.loads
gen_inputs = [json.loads(i) if isinstance(i, str) else i for i in raw_inputs]
check(
    "generation 的 input 带 prompt（Langfuse 原生请求面，两条调用账都在场）",
    len(gen_inputs) == 2
    and all(isinstance(i, dict) and i.get("prompt") == "synthetic" for i in gen_inputs),
    f"实际 {len(gen_inputs)} 笔 choose_call",
)

versions = [getattr(o, "version", None) for o in rows]
check(
    "逐账 version=0.1.0（含 scope 锚）",
    all(v == "0.1.0" for v in versions),
    f"实得 {sorted({str(v) for v in versions})}",
)

span_inputs = [
    json.loads(raw) if isinstance(raw := getattr(o, "input", None), str) else raw
    for o in rows
    if _row_meta(o).get("event_kind") == "press_key" and not _row_meta(o).get("synthetic")
]
check(
    "非模型账 input 为空（占位 uuid 已废，真源在封套与 metadata）",
    bool(span_inputs) and all(i in (None, "", "{}", "null") for i in span_inputs),
    f"实际 {len(span_inputs)} 笔 press_key",
)

# ========== 4. 收尾与全量读回 ==========

main.append("lifecycle", "run_end", _meta(episode_id="", task_id=""), {})
main.flush()

wait_start = time.monotonic()
events: list = []
while time.monotonic() - wait_start < POLL_DEADLINE_SECONDS:
    events = main.read_events()
    if len(events) >= EXPECTED_TOTAL:
        break
    time.sleep(POLL_INTERVAL_SECONDS)
read_wait = time.monotonic() - wait_start
check(
    f"read_events 收齐 {EXPECTED_TOTAL} 笔",
    len(events) == EXPECTED_TOTAL,
    f"实际 {len(events)} 笔，等待 {read_wait:.1f}s",
)
check("shutdown 委托无异常", (main.shutdown() or True) and (child.shutdown() or True))

# ========== 5. 核对：筛选 / 排序 / 封套 / 本地零写入 ==========

by_branch_main = main.read_events({"branch": "main"})
by_branch_child = main.read_events({"branch": restore_branch})
check("branch=main 筛出 8 笔", len(by_branch_main) == 8, f"实际 {len(by_branch_main)}")
check(
    f"branch={restore_branch} 筛出 {len(RESTORE_EVENTS)} 笔（完整后续，含 run_end）",
    len(by_branch_child) == len(RESTORE_EVENTS),
    f"实际 {len(by_branch_child)}",
)
check(
    "task_id=task-1 筛出 4 笔",
    len(main.read_events({"task_id": "task-1"})) == 4,
    "main 线 task 层账：task_start + sense_frame + press_key + choose_call",
)

kinds = [e.kind for e in events]
check("run_start..run_end 全部在场", set(MAIN_EVENTS + RESTORE_EVENTS) <= set(kinds))
keys = [(e.ended_at, e.uuid) for e in events]
check("按 (ended_at, uuid) 升序（双时刻定案：按操作结束时刻排）", keys == sorted(keys))
model_events = [e for e in events if e.kind == "choose_call"]
check(
    "model_call generation 投影无损",
    len(model_events) == 2
    and all(json.loads(e.content)["model"] == "smoke-synthetic" for e in model_events),
    f"实际 {len(model_events)} 笔 choose_call（main + restore 各一）",
)

after = (
    {p: p.stat().st_mtime for p in tracelog.rglob("*") if p.is_file()} if tracelog.exists() else {}
)
new_local = {p for p in after if p not in before} | {
    p for p, mt in after.items() if before.get(p) != mt
}
check(
    "没有事件写入本地 tracelog/",
    not new_local,
    "新增/变动: " + ", ".join(map(str, list(new_local)[:3])) if new_local else "",
)

# ========== 汇总 ==========

failed = [(n, d) for n, ok, d in results if not ok]
passed = len(results) - len(failed)
verdict = "通过" if not failed else f"未通过（{len(failed)} 项失败）"
print(f"\n{'=' * 56}")
print(f"Smoke {verdict} — {passed}/{len(results)}")
for n, d in failed:
    print(f"  FAIL: {n} — {d}")
print(f"run_id   : {run_id}")
print(f"trace_id : {trace_id}")
print(f"Dashboard: {base_url.rstrip('/')}/project/<你的projectId>/traces/{trace_id}")
sys.exit(0 if not failed else 1)
