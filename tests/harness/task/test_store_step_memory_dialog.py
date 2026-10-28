"""动作记忆以状态中的前后 RAM 写入，脚本结局与逐键观察原样保留。"""

from __future__ import annotations

from typing import Any

import pytest
from _harness_fixtures.app_config import DEFAULT_APP_CONFIG
from langgraph.runtime import Runtime
from pydantic import ValidationError

from pokemon_agent.brain import Action, ActionSegment, ScriptCall, Task
from pokemon_agent.direct.brain_tool import Reflector
from pokemon_agent.harness.task.perceive.close_step import close_step
from pokemon_agent.harness.task.perceive.sense import sense
from pokemon_agent.harness.task.perceive.store_step_episode_memory import (
    store_step_episode_memory,
)
from pokemon_agent.harness.task.task_runtime import TaskRuntime
from pokemon_agent.harness.task.task_state import TaskContext, TaskState
from pokemon_agent.schemas.harness import FromHarnessToGameToolPerceiveTaskResp, TraceKind
from pokemon_agent.schemas.memory import ActMemory
from pokemon_agent.world import Facts, PlaceInWorld, RamReadout, TaskObservation, TaskScene


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

    def read_events(self, meta: dict[str, Any] | None = None) -> list[Any]:
        raise AssertionError("写动作记忆不得读取 trace 账")


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
        last_outcome=ActMemory.ScriptOutcome.model_validate(report) if report else None,
        last_observations=[
            ActMemory.Observation.StepObs.model_validate(item)
            for item in (report or {}).get("observations", [])
        ],
        task_ctx=TaskContext(observation=obs),
        after_observation=obs,
    )


def _store(state: TaskState, memory: _Memory, trace: _Trace) -> dict[str, Any]:
    store_step_episode_memory(state, Runtime(context=_runtime(memory, trace)))
    assert len(memory.records) == 1
    return memory.records[0].payload


def test_script_call_carries_observations_and_outcome_into_memory() -> None:
    memory, trace = _Memory(), _Trace()
    observation = {
        "step": 1,
        "place": {"map_id": 12, "x": 13, "y": 8},
        "facing": "north",
        "scene": "dialog",
        "overlay": "dialog",
        "dialog_text": "第二行",
        "ram": {"in_battle": False, "money": 3000, "bag": [], "party": []},
    }
    state = _state(
        Action(script=ScriptCall(name="advance_dialog", args={"max_presses": 10})),
        {"ok": True, "code": "ok", "summary": "对话推到底", "observations": [observation]},
    )

    payload = _store(state, memory, trace)

    assert payload["outcome"] == {"ok": True, "code": "ok", "summary": "对话推到底", "reason": ""}
    assert len(payload["observations"]) == 1
    assert payload["observations"][0]["dialog_text"] == "第二行"
    assert payload["observations"][0]["ram"]["money"] == 3000
    assert "result" not in payload and "dialog" not in payload
    assert trace.events[0].entry.observations[0].dialog_text == "第二行"


def test_key_action_memory_has_no_script_outcome_or_observations() -> None:
    memory, trace = _Memory(), _Trace()
    state = _state(Action(sequence=[ActionSegment(name="up")]), None)

    payload = _store(state, memory, trace)

    assert payload["observations"] == [] and payload["outcome"] is None


def test_memory_without_observations_or_outcome_is_rejected() -> None:
    memory, trace = _Memory(), _Trace()
    state = _state(Action(sequence=[ActionSegment(name="up")]), None)
    payload = _store(state, memory, trace)
    payload.pop("observations")
    payload.pop("outcome")

    with pytest.raises(ValidationError):
        ActMemory.model_validate(payload)


def _ram(money: int) -> RamReadout:
    return RamReadout.model_validate(
        {
            "in_battle": False,
            "covered": True,
            "text_source": "decode",
            "menu": {"current_item": 0, "max_item": 0, "top_x": 0},
            "bag": [{"item_id": 20, "quantity": 1}],
            "party": [{"species": 153, "level": 5, "hp": 10, "max_hp": 20, "status": "ok"}],
            "money": money,
            "decoded": {"dialog_text": "", "options": [], "cursor": ""},
        }
    )


class _SensingGame:
    """一次确定性观察，可模拟 RAM 缺失。"""

    def __init__(self, ram: RamReadout | None) -> None:
        self.ram = ram

    def perceive_task(self) -> FromHarnessToGameToolPerceiveTaskResp:
        return FromHarnessToGameToolPerceiveTaskResp(
            observation=_observation(), frame_png="", ram=self.ram
        )


@pytest.mark.parametrize("present", [True, False])
def test_sense_and_close_keep_ram_with_its_observation(present: bool) -> None:
    trace = _Trace()
    state = _state(Action(sequence=[ActionSegment(name="up")]), None)
    state.action = None
    state.task_ctx = state.task_ctx.model_copy(update={"ram": _ram(9999)})
    expected = _ram(3000) if present else None
    deps = _runtime(_Memory(), trace)
    deps.game = _SensingGame(expected)

    perceived = sense(state, Runtime(context=deps))
    settled = close_step(state.model_copy(update=perceived), Runtime(context=deps))

    assert perceived["after_ram"] == expected
    assert perceived["after_observation"].step == state.total_acts + state.step
    assert trace.events[0].kind == TraceKind.SENSE_FRAME and trace.events[0].ram == expected
    assert settled["task_ctx"].ram == expected
    assert settled["task_ctx"].observation == perceived["after_observation"]
    assert settled["after_ram"] is None and settled["after_observation"] is None


def test_memory_uses_state_ram_without_reading_trace() -> None:
    memory, trace = _Memory(), _Trace()
    state = _state(Action(sequence=[ActionSegment(name="up")]), None)
    before = state.task_ctx.observation
    before.facts.facing = "north"
    before.facts.landmarks = [Facts.Landmark(kind="人", map_id=12, x=13, y=7)]
    state.task_ctx = state.task_ctx.model_copy(update={"ram": _ram(3000)})
    state.after_observation = before.model_copy(update={"step": 1})
    state.after_ram = _ram(2800)

    payload = _store(state, memory, trace)

    assert [event.kind for event in trace.events] == [TraceKind.WRITE_ACT_MEMORY]
    assert payload["before"]["ram"]["money"] == 3000
    assert payload["after"]["ram"]["money"] == 2800
    assert payload["before"]["ram"]["bag"] == [{"item_id": 20, "quantity": 1}]
    assert payload["before"]["facing_object"] == {
        "kind": "人",
        "place": {"map_id": 12, "x": 13, "y": 7},
    }
    assert payload["after"]["facing_object"] == payload["before"]["facing_object"]


@pytest.mark.parametrize(
    ("before_ram", "after_ram"), [(None, _ram(2800)), (_ram(3000), None), (None, None)]
)
def test_missing_ram_stays_empty_in_the_corresponding_snapshot(
    before_ram: RamReadout | None, after_ram: RamReadout | None
) -> None:
    memory, trace = _Memory(), _Trace()
    state = _state(Action(sequence=[ActionSegment(name="up")]), None)
    state.task_ctx = state.task_ctx.model_copy(update={"ram": before_ram})
    state.after_ram = after_ram

    payload = _store(state, memory, trace)

    assert (payload["before"]["ram"] is None) == (before_ram is None)
    assert (payload["after"]["ram"] is None) == (after_ram is None)


def test_consecutive_steps_keep_ram_aligned_when_a_later_readout_is_missing() -> None:
    memory, trace = _Memory(), _Trace()
    deps = _runtime(memory, trace)
    game = _SensingGame(_ram(3000))
    deps.game = game
    runtime = Runtime(context=deps)
    state = _state(Action(sequence=[ActionSegment(name="up")]), None)
    state.action = None

    state = state.model_copy(update=sense(state, runtime))
    state = state.model_copy(update=close_step(state, runtime))
    state.action = Action(sequence=[ActionSegment(name="up")])
    state.step = 1
    game.ram = _ram(2800)
    state = state.model_copy(update=sense(state, runtime))
    store_step_episode_memory(state, runtime)
    state = state.model_copy(update=close_step(state, runtime))
    state.action = Action(sequence=[ActionSegment(name="up")])
    state.step = 2
    game.ram = None
    state = state.model_copy(update=sense(state, runtime))
    store_step_episode_memory(state, runtime)

    first, second = (record.payload for record in memory.records)
    assert first["before"]["ram"]["money"] == 3000
    assert first["after"]["ram"]["money"] == 2800
    assert second["before"]["ram"]["money"] == 2800
    assert second["after"]["ram"] is None
