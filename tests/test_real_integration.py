"""真实链路的端到端集成测试：接真实 `Brain`/`agent_permission`/PyBoy 跑一个
短 episode，逐模块核对产物是否真的落盘。

跟 `tests/test_integration_tool_layer.py` 的区别：那边用 `FakeBrain`（未挂
`@require_permission`），测不出权限运行时初始化顺序这类只在接了真实
`Brain`/`agent_permission` 才会现形的 bug——2026-09-08 就是这样一条真跑
才现形的阻断性 bug（`RunHarness` 的 `plan` 节点在第一次 `dispatch` 之前
就调用受权限守卫的 `Brain.plan_once`，而权限运行时当时只在 `dispatch` 才
初始化）：修复见同日 CHANGELOG。这个文件把"真跑一遍、核对四个模块的落盘
产物"固化成可重复执行的回归测试，而不是每次临时手搓一个脚本。

需要真实网络 + 两个 provider 的 API key，没有就整体跳过（`pytest tests/`
默认跑不需要网络的那些）：

    $env:PYTHONPATH = ""
    $env:ARK_API_KEY = "..."
    $env:DASHSCOPE_API_KEY = "..."
    pytest tests/test_real_integration.py -v -s
"""

from __future__ import annotations

import json
import os
import pathlib

import pytest

pytestmark = pytest.mark.skipif(
    not (os.environ.get("ARK_API_KEY") and os.environ.get("DASHSCOPE_API_KEY")),
    reason="需要 ARK_API_KEY 与 DASHSCOPE_API_KEY 两个真实 key 才能跑真实调用",
)

ROM = "assets/rom"
STATE = "assets/rom.state"
STEPS = 3
GOAL = "向北走一步看看反应"

# 各存储的默认落盘位置（`build.py` 没有覆盖它们，全部用包内默认目录/
# `trace_data/` 目录——跟真实生产装配用的是同一套路径，见各自模块的
# `_DEFAULT_DIR`/`STORAGE_ROOT` 定义）。
_STEP_MEMORY_DIR = (
    pathlib.Path(__file__).resolve().parent.parent
    / "pokemon_agent"
    / "memory"
    / "episode"
    / "memory"
)
_OBJECT_EVENTS_DIR = (
    pathlib.Path(__file__).resolve().parent.parent
    / "pokemon_agent"
    / "memory"
    / "semantic"
    / "object_events"
)
_TRACE_ROOT = pathlib.Path(__file__).resolve().parent.parent / "trace_data"


def _safe(episode_id: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9_-]+", "_", episode_id).strip("_-") or "unknown"


@pytest.fixture(scope="module")
def real_run():
    """真跑一次（模块内的测试共用同一次结果，不用每个断言各跑一遍）。"""
    import time

    from pokemon_agent.build import build_real
    from pokemon_agent.schemas.domain import TaskForHarness

    run_id = f"pytest-realcheck-{time.strftime('%m%d-%H%M%S')}"
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
        goal=GOAL,
        success_criteria="画面上出现能直接证明目标已达成的证据",
        max_steps=STEPS,
    )
    try:
        result = harness.run(run_id, [task])
    finally:
        world.stop()

    outcome = result.outcomes[0]
    return {"run_id": run_id, "episode_id": outcome.episode_id, "outcome": outcome}


def _load_all_events(run_id: str, episode_id: str) -> list[dict]:
    episodes_dir = _TRACE_ROOT / run_id / "episodes"
    events: list[dict] = []
    for path in (episodes_dir / f"{run_id}.jsonl", episodes_dir / f"{_safe(episode_id)}.jsonl"):
        assert path.is_file(), f"缺文件：{path}"
        events += [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return events


def test_run_completes(real_run):
    """harness 模块：一个真实 run 能跑完、给出结算（不强求 success，任务
    本身能不能达成是 brain 判定的事，这里只要求流程没崩）。"""
    outcome = real_run["outcome"]
    assert outcome.steps >= 1
    assert outcome.reason


def test_trace_event_ids_are_globally_contiguous(real_run):
    """harness/trace 模块：run 级 + episode 级骨架事件都在、event_id 全局
    排序后严格连续无缺号无重号。

    两个事件文件各自内部有序，但交叉着分配 id（dispatch 期间的 id 落进
    episode 文件、前后落进 run 文件）——必须按 event_id 全局排序后才能
    判断"是不是真的严格递增、没有缺号/重号"，不能直接比较两个文件拼接后
    的读取顺序。
    """
    events = _load_all_events(real_run["run_id"], real_run["episode_id"])
    events.sort(key=lambda e: e["event_id"])
    ids = [e["event_id"] for e in events]
    assert len(set(ids)) == len(ids), f"event_id 有重号：{ids}"
    assert ids == list(range(ids[0], ids[0] + len(ids))), f"event_id 有缺号：{ids}"

    kinds = {e.get("payload", {}).get("kind", "") for e in events}
    assert {"run_start", "run_end"} <= kinds, f"缺 run 级骨架事件，实有：{kinds}"
    assert {"episode_start", "episode_end"} <= kinds, f"缺 episode 级骨架事件，实有：{kinds}"

    sources = {e.get("source", "") for e in events if e.get("type") == "model_call"}
    assert sources, "没有任何 MODEL_CALL——brain 各技能一次都没被真实调用到"


def test_checkpoint_step_files_are_paired(real_run):
    """harness/checkpoint 模块：run 锚点 + 至少一个 step 存档，state/json
    必须成对存在（不成对的话 CheckpointTool.load() 会拒绝恢复）。"""
    cp_dir = _TRACE_ROOT / real_run["run_id"] / "checkpoints"
    assert (cp_dir / "run.json").is_file(), "run.json 缺失"

    step_dir = cp_dir / "step" / _safe(real_run["episode_id"])
    assert step_dir.is_dir(), f"没有 step 存档目录：{step_dir}"
    state_steps = {p.stem for p in step_dir.glob("*.state")}
    json_steps = {p.stem for p in step_dir.glob("*.json")}
    assert state_steps, "一个 step 存档都没有"
    assert state_steps == json_steps, (
        f"state/json 不成对：state 有 {state_steps}，json 有 {json_steps}"
    )


def test_step_memory_disk_state_is_consistent(real_run):
    """memory 模块（StepMemory）：episode 成功收尾后落盘文件会被蒸馏链清掉
    （`episode_store.py::discard_episode_steps` 的职责）——文件不在不代表
    没写过，这里只要求"状态是自洽的"：要么文件还在且非空（还没蒸馏/失败
    路径），要么已经不在（蒸馏完成，预期行为）。
    """
    path = _STEP_MEMORY_DIR / f"steps-{_safe(real_run['episode_id'])}.jsonl"
    if path.is_file():
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert lines, f"{path} 存在但是空文件——不该出现的中间态"


def test_object_memory_disk_state_is_consistent(real_run):
    """memory 模块（ObjectMemory）：本局任务多半不触发物体交互，没有文件
    是正常的；如果有文件，内容不该是空的。"""
    path = _OBJECT_EVENTS_DIR / f"ep-{_safe(real_run['episode_id'])}.jsonl"
    if path.is_file():
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert lines, f"{path} 存在但是空文件——不该出现的中间态"
