"""task 图：**5 格**，与 run / episode 逐格同形。

`perceive → review_and_judge → plan_task → act → 回 perceive`，判停走
`task_done`。**194 起一键一决策圈**：episode 不再预填链——本层每键自己
"轻感知 → 判停 → 问 chooser 出单键 → 执行"，`act` 出口无条件回 `perceive`
（没有 act 自环）。判停两段：机械三类（世界结束/停摆/预算尽）+ 问模型
"task 目标达成没有"——episode 层判的是**它的**目标，两层判据不混。

**预算**：`NODES_PER_DECISION` / `NODES_PER_PRESS`（与 episode 图同一条公式，
骨架同形）＋ `RECURSION_MARGIN`——贴身限，按本 task 的键预算算。
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from .act import act
from .perceive import perceive
from .plan_task import plan_task
from .review_and_judge import review_and_judge
from .task_done import task_done
from .task_runtime import TaskRuntime
from .task_state import TaskState


def compile_task_graph() -> CompiledStateGraph:
    """把 5 个格装配成 task 图。书写纪律与 episode 图相同（`add_node` 逐行字面量）。"""
    # ========== 1. 注册 5 个格 ==========
    graph = StateGraph(TaskState, context_schema=TaskRuntime)
    graph.add_node("perceive", perceive)
    graph.add_node("review_and_judge", review_and_judge)
    graph.add_node("plan_task", plan_task)
    graph.add_node("act", act)
    graph.add_node("task_done", task_done)

    # ========== 2. 接边——判停出口按 done 分叉，act 出口无条件回 perceive ==========
    graph.set_entry_point("perceive")
    graph.add_edge("perceive", "review_and_judge")
    graph.add_conditional_edges(
        "review_and_judge",
        lambda state: "task_done" if state.done else "plan_task",
        {"plan_task": "plan_task", "task_done": "task_done"},
    )
    graph.add_edge("plan_task", "act")
    graph.add_edge("act", "perceive")
    graph.add_edge("task_done", END)
    return graph.compile()


__all__ = ["compile_task_graph"]
