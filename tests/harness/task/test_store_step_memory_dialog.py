"""`store_step_episode_memory` 的对话字段：脚本调用的对话行进 ActMemory，按键动作落空列表。

**为什么这个文件值钱**：`dialog` 在记忆里是独立字段（不并进 `result`），取值点是
"上一动作的扁平报告"——而按键动作根本没有报告。两条分支必须分开钉住：某天有人把
`last_report` 的取值挪到 `if action.script` 之外，按键记忆就会带上一条脚本的对话。

不调模型、不起模拟器：反射器是真的（`Reflector` 不碰模型），记忆与 trace 是记录型替身。
"""

from __future__ import annotations

from typing import Any

from _harness_fixtures.app_config import DEFAULT_APP_CONFIG
from langgraph.runtime import Runtime

from pokemon_agent.brain import Action, ActionSegment, ScriptCall, Task
from pokemon_agent.direct.brain_tool import Reflector
from pokemon_agent.harness.task.perceive.store_step_episode_memory import (
    store_step_episode_memory,
)
from pokemon_agent.harness.task.task_runtime import TaskRuntime
from pokemon_agent.harness.task.task_state import TaskContext, TaskState
from pokemon_agent.schemas.memory import ActMemory
from pokemon_agent.world import PlaceInWorld, TaskObservation, TaskScene


class _Memory:
    """记录型记忆口：只收 `memorize` 的载荷。"""

    def __init__(self) -> None:
        self.records: list[Any] = []

    def memorize(self, req: Any) -> None:  # noqa: ANN401
        self.records.extend(req.records)


class _Trace:
    """记录型记账口。"""

    def __init__(self) -> None:
        self.events: list[Any] = []

    def append(self, req: Any) -> None:  # noqa: ANN401
        self.events.append(req)


def _runtime(memory: _Memory, trace: _Trace) -> TaskRuntime:
    """只用到反射 / 记忆 / 记账三口的 runtime；其余 Port 传 None（dataclass 不校验）。"""
    return TaskRuntime(  # type: ignore[arg-type]
        config=DEFAULT_APP_CONFIG,
        game=None,
        chooser=None,
        judger=None,
        memory=memory,
        reflector=Reflector(),
        task_summarizer=None,
        trace=trace,
        reviewer=None,
    )


def _observation() -> TaskObservation:
    return TaskObservation(
        facts={"overlay": "none"},
        step=0,
        scene=TaskScene.WALK,
        place=PlaceInWorld(map_id=12, x=13, y=8),
    )


def _state(action: Action, report: dict[str, Any] | None) -> TaskState:
    obs = _observation()
    return TaskState(
        run_id="r",
        episode_id="ep",
        entry_id="e1",
        task=Task(task_id="t1", goal="走到商店", success_criteria="进店", max_steps=5),
        total_acts=0,
        action=action,
        last_report=report,
        task_ctx=TaskContext(observation=obs),
        after_observation=obs,
    )


def _store(state: TaskState, memory: _Memory, trace: _Trace) -> dict[str, Any]:
    store_step_episode_memory(state, Runtime(context=_runtime(memory, trace)))
    assert len(memory.records) == 1
    return memory.records[0].payload


def test_script_call_carries_dialog_lines_into_the_memory() -> None:
    """脚本动作：报告顶层的对话行原样进 `dialog`；结局码仍只住 `result`。"""
    memory, trace = _Memory(), _Trace()
    state = _state(
        Action(script=ScriptCall(name="advance_dialog", args={"max_presses": 10})),
        {
            "ok": True,
            "code": "ok",
            "summary": "对话推到底",
            "dialog": ["第一行", "第二行"],
            "events": [],
            "calls": [],
        },
    )

    payload = _store(state, memory, trace)

    assert payload["dialog"] == ["第一行", "第二行"]
    # 扁平报告的 `summary` 在顶层，`result_line` 只从 `data` 里找它——所以 `result`
    # 只剩结局码。这是改动前就有的行为（本任务不动它），留在这里是为了说明
    # "对话没有并进 result"。
    assert payload["result"] == "ok"
    assert trace.events[0].entry.dialog == ["第一行", "第二行"], "写账里是同一份"


def test_key_action_memory_keeps_empty_dialog() -> None:
    """按键动作：没有报告，`dialog` 落默认空列表（不继承上一条脚本的对话）。"""
    memory, trace = _Memory(), _Trace()
    state = _state(Action(sequence=[ActionSegment(name="up")]), None)

    payload = _store(state, memory, trace)

    assert payload["dialog"] == []
    assert payload["result"] == ""


def test_script_call_without_dialog_keeps_empty_list() -> None:
    """脚本报告里没有 `dialog` 键（或空列表）：记忆里同样是空列表。"""
    memory, trace = _Memory(), _Trace()
    state = _state(
        Action(script=ScriptCall(name="walk_to", args={"x": 5, "y": 2})),
        {"ok": True, "code": "ok", "events": [], "calls": []},
    )

    assert _store(state, memory, trace)["dialog"] == []


def test_old_memory_without_dialog_reads_as_empty_list() -> None:
    """旧记忆文件缺 `dialog` 字段：按默认值读出空列表，不需要兼容逻辑。"""
    memory, trace = _Memory(), _Trace()
    state = _state(
        Action(script=ScriptCall(name="advance_dialog", args={"max_presses": 10})),
        {"ok": True, "code": "ok", "dialog": ["第一行"], "events": []},
    )
    payload = _store(state, memory, trace)

    legacy = {key: value for key, value in payload.items() if key != "dialog"}
    assert "dialog" not in legacy

    assert ActMemory.model_validate(legacy).dialog == []
