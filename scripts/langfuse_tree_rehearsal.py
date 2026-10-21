"""mock 三件套（假大脑 / 假世界 / 假记忆）+ 真的三张图 harness 写本机 Langfuse。

目的：看**真实 harness** 发账顺序下的树形（smoke 是手拼账，这里不是）。
main 跑一个完整 run（自动存 run / episode / task 三级档），再分别从
episode 级与 task 级存档各恢复一条新执行线跑到 run 结束——三种树形一次看全。

用法（本机 Langfuse v4 运行中，`LANGFUSE_*` 在 `.env` 或 shell 里）：

    .venv/Scripts/python.exe scripts/langfuse_tree_rehearsal.py

红线：只连 `LANGFUSE_BASE_URL`（校验必须是 localhost）；不起 PyBoy / ROM /
真实模型；不打印密钥。模型与模拟器全是假件（`tests/_fake_run.py`）。
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from _fake_run import GOAL, build_fake  # noqa: E402

from pokemon_agent.env import load_env_file  # noqa: E402
from pokemon_agent.harness import RunRuntime  # noqa: E402
from pokemon_agent.harness.checkpoint import (  # noqa: E402
    CheckpointManifest,
    list_checkpoints,
    restore_run,
)
from pokemon_agent.trace.langfuse_support import (  # noqa: E402
    build_client_from_environment,
    read_observations,
)

SETTLE_WAIT_SECONDS = 5.0
POLL_DEADLINE_SECONDS = 60.0
POLL_INTERVAL_SECONDS = 2.0

load_env_file(REPO / ".env")

base_url = os.environ.get("LANGFUSE_BASE_URL", "")
host = base_url.split("//", 1)[-1].split(":", 1)[0].split("/", 1)[0]
if host not in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
    print(f"拒绝：LANGFUSE_BASE_URL 非本机（{base_url or '未设置'}）")
    sys.exit(2)

run_id = f"tree-{uuid.uuid4().hex[:6]}"
tmp = Path(tempfile.mkdtemp(prefix="lf_tree_"))
print(f"run_id={run_id}\n临时目录={tmp}\n")

# ---- 1. main：mock 组件 + 真三张图，跑完整一局（自动存三级档） ----

main = build_fake(tmp, run_id=run_id, checkpoints=True, backend="langfuse")
main.harness.run(run_id, [GOAL])
main.trace.flush()
print("main 线跑完（run_end 自带 flush）")


def _path(manifest: CheckpointManifest) -> Path:
    return tmp / "checkpoints" / run_id / manifest.checkpoint_id / "manifest.json"


def _build(branch: str) -> RunRuntime:
    """恢复装配函数：同一个存档根，只换分支名（与真机 build_real 同形）。"""
    return build_fake(
        tmp, run_id=run_id, checkpoints=True, backend="langfuse", branch=branch
    ).run_rt


# ---- 2. 两条恢复线：episode 级 + task 级 ----

manifests = list_checkpoints(tmp / "checkpoints", run_id)
ep_level = [m for m in manifests if m.level == "episode" and m.episode_id.endswith("-ep2")]
task_level = [m for m in manifests if m.level == "task" and m.episode_id.endswith("-ep1")]
assert ep_level, "没有 episode 级存档——存档链坏了"
assert len(task_level) >= 2, "task 级存档不够——存档链坏了"

for label, manifest in (("episode 级", ep_level[0]), ("task 级", task_level[1])):
    print(f"从 {label} 存档恢复：{manifest.checkpoint_id}")
    outcomes, *_ = restore_run(_path(manifest), _build)
    assert outcomes, f"{label} 恢复后没有跑出任何 episode"

# ---- 3. 等 OTEL 批量导出落地，经 API 读回真实树 ----

print(f"\n故意等待 {SETTLE_WAIT_SECONDS:.0f}s（等批量导出）…")
time.sleep(SETTLE_WAIT_SECONDS)

client = build_client_from_environment()
trace_id = client.create_trace_id(seed=run_id)

deadline = time.monotonic() + POLL_DEADLINE_SECONDS
rows: list[object] = []
while time.monotonic() < deadline:
    rows = read_observations(client, trace_id)
    fakes = [
        o
        for o in rows
        if isinstance(getattr(o, "metadata", None), dict) and o.metadata.get("synthetic")
    ]
    if len(fakes) >= 3:  # episode 级 1 层 + task 级 2 层
        break
    time.sleep(POLL_INTERVAL_SECONDS)


def _meta_of(obs: object) -> dict[str, Any]:
    value = getattr(obs, "metadata", None)
    return value if isinstance(value, dict) else {}


def _start(obs: object) -> float:
    value = getattr(obs, "start_time", None)
    return value.timestamp() if value is not None else 0.0


def _branch_of(obs: object) -> str:
    """账所属分支：scope 锚在顶层 metadata，事件账嵌在 event_meta 里。

    step scope 删除后事件账的顶层 metadata 只有 event_kind/event_meta 四键
    （langfuse_trace._observation_metadata），只看顶层会把每支线的行数
    压到"仅锚数"（3/2/1），run_end 最晚性检查也随之恒跳过。
    """
    meta = _meta_of(obs)
    value = meta.get("branch")
    if isinstance(value, str) and value:
        return value
    event_meta = meta.get("event_meta")
    return str(event_meta.get("branch", "")) if isinstance(event_meta, dict) else ""


by_id = {o.id: o for o in rows}
children: dict[str | None, list[object]] = {}
for obs in rows:
    parent = getattr(obs, "parent_observation_id", None) or None
    if parent is not None and parent not in by_id:
        parent = None  # SDK 的随机 remote parent（AS_ROOT）按顶层渲染
    children.setdefault(parent, []).append(obs)


def _render(obs: object, depth: int, lines: list[str]) -> None:
    meta = _meta_of(obs)
    fake = " [fake]" if meta.get("synthetic") else ""
    branch = meta.get("branch", "")
    lines.append(f"{'    ' * depth}- {getattr(obs, 'name', '?')}{fake}  ({branch})")
    for child in sorted(children.get(obs.id, []), key=_start):
        _render(child, depth + 1, lines)


print(f"\ntrace_id : {trace_id}")
print(f"Dashboard: {base_url.rstrip('/')}/project/<projectId>/traces/{trace_id}\n")
tree_lines: list[str] = []
for root_obs in sorted(children.get(None, []), key=_start):
    _render(root_obs, 0, tree_lines)
print("\n".join(tree_lines))

# ---- 4. 关键契约核对 ----

print("\n核对:")
failures: list[str] = []
for root_obs in children.get(None, []):
    branch = _branch_of(root_obs)
    own = [o for o in rows if _branch_of(o) == branch]
    fakes = [o for o in own if _meta_of(o).get("synthetic")]
    ends = [o for o in own if getattr(o, "name", "") == "run_end"]
    if not own:
        continue
    if branch == "main" and fakes:
        failures.append(f"{branch}: main 线不该有伪造锚")
    if branch != "main":
        if len(fakes) not in (1, 2):
            failures.append(f"{branch}: 伪造锚 {len(fakes)} 层（应为 1 或 2）")
        names = [o.name for o in fakes]
        if any("(fake)" not in n for n in names):
            failures.append(f"{branch}: 伪造锚缺 (fake) 后缀: {names}")
    if ends and _start(ends[0]) != max(_start(o) for o in own):
        failures.append(f"{branch}: run_end 不是本线最晚的 start_time")
    print(f"  {branch}: {len(own)} 行, 伪造锚 {[o.name for o in fakes]}")

print(f"\n{'通过' if not failures else '失败: ' + '; '.join(failures)}")
sys.exit(0 if not failures else 1)
