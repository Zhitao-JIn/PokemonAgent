"""task 图的装配冒烟：5 格同形骨架能编译、预算公式成立。

逐格行为由真机核对与各单元自身的断言保证；这里只钉住"图真的长成设计的样子"
与"预算换算公式"。
"""

from __future__ import annotations

from types import SimpleNamespace

from pokemon_agent.brain import Task
from pokemon_agent.config import NODES_PER_DECISION, NODES_PER_PRESS, RECURSION_MARGIN
from pokemon_agent.harness.task import compile_task_graph
from pokemon_agent.harness.task.task_entry import begin_task, task_budget
from pokemon_agent.schemas.harness import TraceKind
from pokemon_agent.schemas.harness.domain import TaskInput


def _input(max_steps: int = 10) -> TaskInput:
    return TaskInput(
        run_id="r1",
        episode_id="r1-ep1",
        task=Task(task_id="t1", goal="g", success_criteria="c", max_steps=max_steps),
        total_acts=7,
    )


def test_task_graph_has_the_five_cells() -> None:
    """5 格同形骨架：节点集与 episode 图逐格同名（除 plan/done 的层后缀）。"""
    g = compile_task_graph()
    nodes = set(g.get_graph().nodes)
    assert nodes == {
        "perceive",
        "review_and_judge",
        "plan_task",
        "act",
        "task_done",
        "__start__",
        "__end__",
    }, nodes


def test_task_budget_is_keys_times_cells_plus_margin() -> None:
    """贴身限 = 键预算 × (决策 3 格 + act 1 格) + 余量——每键最坏 4 个 superstep。"""
    assert task_budget(_input(10)) == 10 * (NODES_PER_DECISION + NODES_PER_PRESS) + RECURSION_MARGIN


class _Trace:
    def __init__(self) -> None:
        self.appended: list = []

    def append(self, req) -> None:  # noqa: ANN001
        self.appended.append(req)


def test_begin_task_takes_no_frame() -> None:
    """入口只落一条 `task_start`、装初值，**不取帧**——开局帧由图内 perceive 的 `sense` 取。"""
    trace = _Trace()
    state = begin_task(SimpleNamespace(trace=trace, checkpointer=None), _input())

    assert state.task_ctx.observation is None
    assert state.after_observation is None and state.action is None
    assert state.step == 0 and state.total_acts == 7
    assert [r.kind for r in trace.appended] == [TraceKind.TASK_START]
    assert trace.appended[0].meta["task_id"] == "t1" and trace.appended[0].meta["step"] == 0
