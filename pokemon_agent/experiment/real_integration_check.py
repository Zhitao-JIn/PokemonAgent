"""真实链路的端到端集成核对：跑一个短 episode，逐模块核对产物落地。

跟 `run_episode.py` 的区别：那个脚本只关心"任务跑没跑成"；这个脚本是
"跑完之后，harness/checkpoint/trace/memory 四个模块各自该落的盘是不是真的
落了"——picking up on 0908 的发现：Mock/Fake 驱动的集成测试（`tests/
test_integration_tool_layer.py`）测不出权限运行时初始化顺序这类只在接了
真实 `Brain`/`agent_permission` 才会现形的 bug，所以需要一条真跑真查的路径，
留作以后每次改完 harness/checkpoint 就手动跑一遍的核对清单。

用法（PowerShell，需要真实网络与两个 API key）：

    $env:PYTHONPATH = ""
    $env:ARK_API_KEY = "..."
    $env:DASHSCOPE_API_KEY = "..."
    python -m pokemon_agent.experiment.real_integration_check
    python -m pokemon_agent.experiment.real_integration_check --steps 3 --goal "向北走一步看看反应"

跑完打印一张模块级 PASS/FAIL 表，非零退出码表示至少一项核对未通过。
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

ROM = "assets/rom"
STATE = "assets/rom.state"

# 各存储的默认落盘位置（`build.py` 没有覆盖它们，全部用包内默认目录/
# `trace_data/` 目录——跟真实生产装配用的是同一套路径，见各自模块的
# `_DEFAULT_DIR`/`STORAGE_ROOT` 定义）。
_STEP_MEMORY_DIR = (
    pathlib.Path(__file__).resolve().parent.parent / "memory" / "episode" / "memory"
)
_OBJECT_EVENTS_DIR = (
    pathlib.Path(__file__).resolve().parent.parent / "memory" / "semantic" / "object_events"
)
_TRACE_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent / "trace_data"


def _safe(episode_id: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9_-]+", "_", episode_id).strip("_-") or "unknown"


class Check:
    """一项核对的结果：模块名 + 通过与否 + 一句话说明。"""

    def __init__(self, module: str, ok: bool, detail: str) -> None:
        self.module = module
        self.ok = ok
        self.detail = detail


def check_environment() -> None:
    missing = [k for k in ("ARK_API_KEY", "DASHSCOPE_API_KEY") if not os.environ.get(k)]
    if missing:
        print(f"错误：缺少环境变量 {missing}，两个 provider 都要真实 key 才能跑真实调用。")
        sys.exit(1)
    if "CLAUDE_RUN_ID" not in os.environ:
        import time

        os.environ["CLAUDE_RUN_ID"] = f"realcheck-{time.strftime('%m%d-%H%M%S')}"


def check_trace(run_id: str, episode_id: str) -> list[Check]:
    """harness/trace 模块：run 级与 episode 级事件都要有、event_id 全局严格单调。"""
    checks: list[Check] = []
    episodes_dir = _TRACE_ROOT / run_id / "episodes"
    run_file = episodes_dir / f"{run_id}.jsonl"
    ep_file = episodes_dir / f"{_safe(episode_id)}.jsonl"

    all_events: list[dict] = []
    for path in (run_file, ep_file):
        if not path.is_file():
            checks.append(Check("trace", False, f"缺文件：{path}"))
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                all_events.append(json.loads(line))

    if not all_events:
        checks.append(Check("trace", False, "两个事件文件都读不到内容"))
        return checks

    # 两个文件各自内部有序，但交叉着分配 id（dispatch 期间的 id 落进 episode
    # 文件、前后落进 run 文件）——按 event_id 全局排序后才能看出"是不是真的
    # 严格递增、没有缺号/重号"，不能直接比较两个文件拼接后的读取顺序。
    all_events.sort(key=lambda e: e["event_id"])
    ids = [e["event_id"] for e in all_events]
    no_dupes = len(set(ids)) == len(ids)
    no_gaps = ids == list(range(ids[0], ids[0] + len(ids)))
    monotonic = no_dupes and no_gaps
    checks.append(
        Check(
            "trace",
            monotonic,
            f"event_id 全局排序后{'严格连续无缺号无重号' if monotonic else '有缺号或重号'}："
            f"{ids}",
        )
    )

    kinds = {e.get("payload", {}).get("kind", "") for e in all_events}
    expect_run = {"run_start", "run_end"}
    expect_ep = {"episode_start", "episode_end"}
    checks.append(
        Check(
            "trace",
            expect_run <= kinds,
            f"run 级骨架事件{'齐全' if expect_run <= kinds else f'缺 {expect_run - kinds}'}",
        )
    )
    checks.append(
        Check(
            "trace",
            expect_ep <= kinds,
            f"episode 级骨架事件{'齐全' if expect_ep <= kinds else f'缺 {expect_ep - kinds}'}",
        )
    )

    sources = {e.get("source", "") for e in all_events if e.get("type") == "model_call"}
    checks.append(Check("trace", len(sources) > 0, f"MODEL_CALL 来源（brain 各技能）：{sources or '无'}"))
    return checks


def check_checkpoint(run_id: str, episode_id: str) -> list[Check]:
    """harness/checkpoint 模块：run 锚点 + 至少一个 step 存档，state/json 成对。"""
    checks: list[Check] = []
    cp_dir = _TRACE_ROOT / run_id / "checkpoints"
    run_json = cp_dir / "run.json"
    exists = run_json.is_file()
    checks.append(Check("checkpoint", exists, f"run.json {'存在' if exists else '缺失'}"))

    step_dir = cp_dir / "step" / _safe(episode_id)
    if not step_dir.is_dir():
        checks.append(Check("checkpoint", False, f"没有 step 存档目录：{step_dir}"))
        return checks

    states = sorted(step_dir.glob("*.state"))
    jsons = sorted(step_dir.glob("*.json"))
    state_steps = {p.stem for p in states}
    json_steps = {p.stem for p in jsons}
    paired = state_steps == json_steps and len(states) > 0
    checks.append(
        Check(
            "checkpoint",
            paired,
            f"{len(states)} 个 step 存档，state/json {'成对' if paired else '不成对——恢复会拒绝'}"
            f"（steps={sorted(state_steps, key=int) if state_steps else []}）",
        )
    )
    return checks


def check_step_memory(episode_id: str, expected_min_steps: int) -> list[Check]:
    """memory 模块（StepMemory）：episode 跑完会被蒸馏链清掉落盘文件，这是
    **预期行为**（`episode_store.py::discard_episode_steps` 的职责），文件
    不在不代表没写过——这里退化成"报告观察到的状态"而不是硬性 PASS/FAIL。
    """
    path = _STEP_MEMORY_DIR / f"steps-{_safe(episode_id)}.jsonl"
    if not path.is_file():
        return [
            Check(
                "memory(step)",
                True,
                "steps-*.jsonl 已不在——若 episode 成功收尾这是预期（蒸馏后清盘），"
                "不是漏写；若想验证真写过，在跑之前给 discard 打个断点或改脚本",
            )
        ]
    n = len(path.read_text(encoding="utf-8").splitlines())
    return [Check("memory(step)", n >= expected_min_steps, f"落盘 {n} 条 step 记录（未蒸馏/清盘）")]


def check_object_memory(episode_id: str) -> list[Check]:
    """memory 模块（ObjectMemory）：三步随手走路多半不触发交互，没有文件是
    正常的——这里同样只报告观察，不当失败项。
    """
    path = _OBJECT_EVENTS_DIR / f"ep-{_safe(episode_id)}.jsonl"
    if not path.is_file():
        return [Check("memory(object)", True, "本局没有产生任何物体交互事件（正常，任务未涉及）")]
    n = len(path.read_text(encoding="utf-8").splitlines())
    return [Check("memory(object)", True, f"落盘 {n} 条交互事件")]


def main() -> int:
    check_environment()
    run_id = os.environ["CLAUDE_RUN_ID"]

    steps = 3
    goal = "向北走一步看看反应"
    args = sys.argv[1:]
    if "--steps" in args:
        steps = int(args[args.index("--steps") + 1])
    if "--goal" in args:
        goal = args[args.index("--goal") + 1]

    from pokemon_agent.build import build_real
    from pokemon_agent.schemas.domain import TaskForHarness

    print(f"🔍 真实集成核对 run_id={run_id} steps={steps} goal={goal!r}")
    harness, trace, world, tools = build_real(
        ROM,
        STATE,
        vision_model="qwen3.8-max",
        text_model="qwen-plus",
        max_tokens=25600,
        run_id=run_id,
    )
    task = TaskForHarness(
        task_id="realcheck",
        goal=goal,
        success_criteria="画面上出现能直接证明目标已达成的证据",
        max_steps=steps,
    )
    try:
        result = harness.run(run_id, [task])
    finally:
        world.stop()

    outcome = result.outcomes[0]
    episode_id = outcome.episode_id
    print(f"结果: success={outcome.success} steps={outcome.steps} reason={outcome.reason}")
    print(f"episode_id={episode_id}\n")

    all_checks: list[Check] = []
    all_checks += check_trace(run_id, episode_id)
    all_checks += check_checkpoint(run_id, episode_id)
    all_checks += check_step_memory(episode_id, expected_min_steps=1)
    all_checks += check_object_memory(episode_id)

    print("模块核对结果：")
    failed = 0
    for c in all_checks:
        mark = "✅" if c.ok else "❌"
        print(f"  {mark} [{c.module}] {c.detail}")
        if not c.ok:
            failed += 1

    print(f"\n{'全部通过' if failed == 0 else f'{failed} 项未通过'}（共 {len(all_checks)} 项）")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
