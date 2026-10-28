"""预算收尾保存已有逐步观察推导出的机械事实。"""

from types import SimpleNamespace

from langgraph.runtime import Runtime

from pokemon_agent.brain import Task
from pokemon_agent.harness.task.task_done.mechanical import mechanical_summary
from pokemon_agent.harness.task.task_state import TaskContext, TaskState
from pokemon_agent.memory.facts import task_facts, task_step_range
from pokemon_agent.schemas.harness.domain import Termination
from pokemon_agent.schemas.memory import ActMemory


class _Memory:
    def __init__(self) -> None:
        self.records = []

    def memorize(self, req) -> None:
        self.records.extend(req.records)


class _Trace:
    def append(self, _req) -> None:
        return None


def _snapshot(step: int, scene: str) -> ActMemory.Observation:
    return ActMemory.Observation.model_validate(
        {
            "step": step,
            "scene": scene,
            "facts": {"scene": scene},
            "place": {"map_id": 1, "x": 0, "y": 0},
        }
    )


def _entry() -> ActMemory:
    return ActMemory(
        before=_snapshot(37, "walk"),
        action="east",
        after=_snapshot(38, "town"),
        step=37,
        episode_id="ep1",
        task_id="task1",
        observations=[],
        outcome=None,
    )


def _state(entries: list[ActMemory]) -> TaskState:
    return TaskState(
        run_id="run1",
        episode_id="ep1",
        entry_id="goal1",
        task=Task(task_id="task1", goal="到城镇", success_criteria="换图", max_steps=2),
        total_acts=37,
        step=1,
        termination=Termination.BUDGET_EXHAUSTED,
        task_ctx=TaskContext(act_memories=entries),
    )


def test_budget_task_summary_matches_the_llm_path_mechanical_material() -> None:
    entry = _entry()
    memory_tool, trace = _Memory(), _Trace()
    runtime = Runtime(context=SimpleNamespace(memory=memory_tool, trace=trace))

    result = mechanical_summary(_state([entry]), runtime)
    memory = result["memory"]

    assert memory.facts == task_facts([entry], "task1", "ep1")
    assert memory.facts and all(fact.step == 38 and fact.sub == 0 for fact in memory.facts)
    assert memory.pointers == task_step_range([entry]) == ["37-38"]
    assert memory.index.headline == ""


def test_budget_task_summary_has_empty_evidence_when_no_act_memory_exists() -> None:
    memory_tool = _Memory()
    result = mechanical_summary(
        _state([]), Runtime(context=SimpleNamespace(memory=memory_tool, trace=_Trace()))
    )

    assert result["memory"].facts == []
    assert result["memory"].pointers == []
