"""run 图的装配：6 个节点 + 3 条条件边 + 挂在 `episode` 那格上的 `error_handler`。

拓扑（步 2 起 `dispatch` 与 `reflect` 之间多了一个 `episode` 节点）：

    begin ──→ plan ──→ dispatch ──→ episode ──→ reflect ──┬─(失败且重试未耗尽)─→ dispatch
                  ↑                                        │        （重试就是再派发一次 episode）
                  │                                        └─(否则：弹出)─→ review
                  └────── continue / retry ────────────────────────────────┤
                    (done / plan 连续失败)                                └─ stop → END

**`episode` 是"两张图怎么连"的落点**（`PLAN_graph_composition.md` §6 步 2 / D1-①）：
`dispatch` 退成**纯前置**（生成 `episode_id`、`attempts+1`、把父侧的 `task` /
`episode_goals` 写进 state、刷 `run_state_snapshot`），派发本身由 `episode` 节点做。

- `error_handler` 挂在这一格上（F4 实测：handler 拿到的是**父 state**，返回
  `Command(goto="reflect", update=…)` 时流程正常继续）——这就是原先 `dispatch` 里
  那句 `except AgentError` 的官方落点，"单局异常不崩掉整个 run" 的契约没有丢。
- 子图步数**是否**计入父 limit：F5 说"计"，但那只对形态 A（子图当 `add_node` 的函数直挂）
  成立；本仓是形态 B（节点里 `graph.invoke`），探针 X5 实测父子各算各的。所以 run 级
  不再去算 episode 那一笔——只给一个可调的**闸门常量**（`run_entry.RUN_RECURSION_LIMIT`），
  贴身的限归内层 `episode_entry.episode_budget()`。
- 观测台零影响（F9）：它吃 trace 事件，不吃 graph stream。

**步 4 起本模块是"只有 import 与装配"**：6 个节点各自住在同级的 `<节点名>.py`
（命名规则 §5.3-5：节点文件名 = 这里 `add_node` 的字面量），本模块只负责
"把哪些节点按什么顺序接起来"。

`add_node` **逐行写字面量**：顶层即流程，且 `scripts/check_graph_phases.py` 靠
`ast` 抽这些字面量做机械核对（图序 + "每个节点名恰好一个实现文件"）。
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ..deps import HarnessDeps
from .begin import begin
from .dispatch import dispatch, episode_error_handler
from .episode import episode
from .plan import plan
from .reflect import reflect
from .review import review
from .run_state import RunState


def compile_run_graph() -> CompiledStateGraph:
    """把 6 个节点与它们之间的边装配成图，返回编译好的对象。

    **不带参数**（步 4 起）：节点名 → 节点函数那张表就是同级的 6 个模块，
    本模块 import 它们即可——装配与实现分居两层，一张表两处维护的窗口关掉了。

    `episode_error_handler` 是本图唯一一个"只在出错时才跑"的节点——它不当顶点用，
    只交给 `add_node(..., error_handler=)`（F4）。

    `plan` 出口三路：`dispatch`（压栈或无事）/ `END`（done）/ `review`（plan 连续
    失败，或 `auto_decide_done=False` 时栈空到此）；`reflect` 出口两路（重试 / 收尾）；
    `review` 出口两路（继续 → `plan` / 停止 → `END`）。
    `START` 条件边按 `resume_episode` 分流——恢复时跳过 `begin` 与 `plan`
    （它们的产物早已在存档里，重问一遍既多花一次调用又可能与存档不一致）。

    **`context_schema` 声明成 `HarnessDeps`**（全图唯一的 context，F10）：
    `run_entry.new_run()` 用 `invoke(..., context=deps)` 递进来，episode 那只子图
    通过它拿到同一份依赖与账。类型参数只能填它——`scripts/check_graph_phases.py`
    有机械核对。
    """
    graph = StateGraph(RunState, context_schema=HarnessDeps)
    graph.add_node("begin", begin)
    graph.add_node("plan", plan)
    graph.add_node("dispatch", dispatch)
    # `episode`：派发这一局（内部是 episode 那只子图），异常由 handler 兜成失败结算。
    graph.add_node("episode", episode, error_handler=episode_error_handler)
    graph.add_node("reflect", reflect)
    graph.add_node("review", review)
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


__all__ = ["compile_run_graph"]
