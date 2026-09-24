"""run 图的装配：6 格 + 1 条条件边（一局一圈）。

    begin → perceive → review_and_judge ─done→ run_done → END
                              └─否则→ plan_run → act → perceive

- `review_and_judge` 是**唯一的停机判定点**：收上一局结算、盖章，再机械三类 + 问模型。
  首圈 `outcome` 为 None，只做机械判定。
- `plan_run` 只管目标表，不判停；规划完没有 PENDING 就 fail-fast。
- `act` 派一局；整局抛错由 `act` 自己接住、记 `episode_error`，
  `AgentError` 兜成 `ERROR` 结算，同样回 `perceive`。
- 失败盖 FAILED（终态），重试是 `plan_run` 的显式决定（把 FAILED 重开成 PENDING）。

`add_node` 逐行写字面量：顶层即流程。
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from .act import act
from .begin import begin
from .perceive import perceive
from .plan_run import plan_run
from .review_and_judge import review_and_judge
from .run_done import run_done
from .run_state import RunState
from .runtime import RunRuntime


def compile_run_graph() -> CompiledStateGraph:
    """把 6 个格与它们之间的边装配成图，返回编译好的对象。

    `context_schema` 是 `RunRuntime`：`run_entry.new_run()` 经 `invoke(..., context=deps)` 递入。
    """
    # ========== 1. 注册 6 个格 ==========
    graph = StateGraph(RunState, context_schema=RunRuntime)
    graph.add_node("begin", begin)
    graph.add_node("perceive", perceive)
    graph.add_node("review_and_judge", review_and_judge)
    graph.add_node("plan_run", plan_run)
    graph.add_node("act", act)
    graph.add_node("run_done", run_done)

    # ========== 2. 接边——判停出口按 done 分叉，act 出口无条件回 perceive ==========
    graph.add_edge(START, "begin")
    graph.add_edge("begin", "perceive")
    graph.add_edge("perceive", "review_and_judge")
    graph.add_conditional_edges(
        "review_and_judge",
        lambda state: "run_done" if state.done else "plan_run",
        {"plan_run": "plan_run", "run_done": "run_done"},
    )
    graph.add_edge("plan_run", "act")
    graph.add_edge("act", "perceive")
    graph.add_edge("run_done", END)
    return graph.compile()


__all__ = ["compile_run_graph"]
