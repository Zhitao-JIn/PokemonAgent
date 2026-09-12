"""run 图的装配：6 个节点 + 3 条条件边。

拓扑（步 2 起 `dispatch` 与 `reflect` 之间多了一个 `episode` 节点）：

    begin ──→ plan ──→ dispatch ──→ episode ──→ reflect ──┬─(失败且重试未耗尽)─→ dispatch
                  ↑                                        │        （直接重试，不经 episode？是——
                  │                                        │         重试就是再派发一次 episode）
                  │                                        └─(否则：弹出)─→ review
                  └────── continue / retry / push ────────────────────────┤
                    (done / plan 连续失败)                                └─ stop → END

**`episode` 是"两张图怎么连"的落点**（`PLAN_graph_composition.md` §6 步 2 / D1-①）：
`dispatch` 退成**纯前置**（生成 `episode_id`、`attempts+1`、把父侧的 `task` /
`episode_goals` 写进 state、刷 `run_state_snapshot`），派发本身由 `episode` 节点做。
- `error_handler` 挂在这一格上（F4 实测：handler 拿到的是**父 state**，返回
  `Command(goto="reflect", update=…)` 时流程正常继续）——这就是原先 `dispatch` 里
  那句 `except AgentError` 的官方落点，"单局异常不崩掉整个 run" 的契约没有丢。
- 子图步数**计入父图 `recursion_limit`**（F5；节点里嵌套 invoke 也一样，探针 X1），
  所以 run 级的预算覆盖了 episode 的全部内部步数——见 `run_harness.py` 的
  `run_recursion_limit()`。
- 观测台零影响（F9）：它吃 trace 事件，不吃 graph stream。

**步 2 的形态**：节点仍是 `RunHarness` 的方法（`nodes[...]` 里传进来），本模块只负责
"把哪些节点按什么顺序接起来"；episode 那只子图在步 3 逐域展开、run 这 6 个在步 4
搬成自由函数（见 `PLAN_graph_composition.md` §6）。

`add_node` **逐行写字面量**：顶层即流程，且 `scripts/check_graph_phases.py` 靠
`ast` 抽这些字面量做机械核对。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ..deps import HarnessDeps
from .state import RunState

NodeFn = Callable[[RunState], dict]
"""一个节点的形状：读 state 全量，只回**状态增量**。"""


def compile_run_graph(nodes: Mapping[str, NodeFn]) -> CompiledStateGraph:
    """把 6 个节点与它们之间的边装配成图，返回编译好的对象。

    `nodes` 的键就是节点名（与 `add_node` 的字面量逐字相同），值是节点函数。
    `episode_error_handler` 是本图唯一一个"只在出错时才跑"的节点——它不当顶点用，
    只交给 `add_node(..., error_handler=)`（F4）。

    `plan` 出口三路：`dispatch`（压栈或无事）/ `END`（done）/ `review`（plan 连续
    失败，或 `auto_decide_done=False` 时栈空到此）；`reflect` 出口两路（重试 / 收尾）；
    `review` 出口两路（继续 → `plan` / 停止 → `END`）。
    `START` 条件边按 `resume_episode` 分流——恢复时跳过 `begin` 与 `plan`
    （它们的产物早已在存档里，重问一遍既多花一次调用又可能与存档不一致）。

    **`context_schema` 声明成 `HarnessDeps`**（全图唯一的 context，F10）：
    `RunHarness.run()` 用 `invoke(..., context=deps)` 递进来，episode 那只子图
    通过它拿到同一份依赖与账。类型参数只能填它——`scripts/check_graph_phases.py`
    有机械核对。
    """
    graph = StateGraph(RunState, context_schema=HarnessDeps)
    graph.add_node("begin", nodes["begin"])
    graph.add_node("plan", nodes["plan"])
    graph.add_node("dispatch", nodes["dispatch"])
    # `episode`：派发这一局（内部是 episode 那只子图），异常由 handler 兜成失败结算。
    graph.add_node("episode", nodes["episode"], error_handler=nodes["episode_error_handler"])
    graph.add_node("reflect", nodes["reflect"])
    graph.add_node("review", nodes["review"])
    graph.add_conditional_edges(
        START,
        lambda state: "dispatch" if state.resume_episode is not None else "begin",
        {"begin": "begin", "dispatch": "dispatch"},
    )
    graph.add_edge("begin", "plan")
    graph.add_conditional_edges(
        "plan",
        lambda s: (
            "review"
            if s.plan_failed
            else END
            if s.done
            # 栈空到这里还没被判 done，只会是 `auto_decide_done=False`——
            # `dispatch` 断言非空栈，这种情形改路由去 `review` 问人（要不要
            # 压新目标、还是 `STOP`），不会撞断言。
            else "review"
            if not s.goals
            else "dispatch"
        ),
        {"dispatch": "dispatch", "review": "review", END: END},
    )
    graph.add_edge("dispatch", "episode")
    graph.add_edge("episode", "reflect")
    graph.add_conditional_edges(
        "reflect",
        lambda s: "dispatch" if _should_retry(s) else "review",
        {"dispatch": "dispatch", "review": "review"},
    )
    graph.add_conditional_edges(
        "review",
        lambda s: END if s.done else "plan",
        {"plan": "plan", END: END},
    )
    return graph.compile()


def _should_retry(state: RunState) -> bool:
    """`reflect` 的出口路由：失败且栈顶还是刚失败的那个目标 → 直连 `dispatch`
    重试（不经 `review`）；否则（成功弹出 / 重试耗尽弹出）→ `review`。

    用 `goals[-1] == task`（字段相等）判断"没弹"：相邻两层内容完全相同的目标
    会把"耗尽弹出"误判成"可重试"，多打一轮后仍会走到 `review`，代价可接受，
    不值得为它引入额外的路由字段。
    """
    return (
        state.outcome is not None
        and not state.outcome.success
        and bool(state.goals)
        and state.goals[-1] == state.task
    )
