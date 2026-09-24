"""episode 图：**5 格**，与 run / task 逐格同形的骨架（一 task 一圈）。

    perceive → review_and_judge ─done→ episode_done → END
                      └─否则→ plan_episode → act → perceive

`perceive` 先吸收上一个 task 的结算再做检索；`plan_episode` 队列空时问
decomposer；`act` 派一个 task 子图。每格的实现住同名文件夹，格入口在文件夹的
`__init__.py`，单元串接语义见 `compose.py`。交界契约（`EpisodeInput` /
`EpisodeOutput`）住 `schemas/harness/domain/episode_io.py`。
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from .act import act
from .episode_done import episode_done
from .episode_runtime import EpisodeRuntime
from .episode_state import EpisodeRunState
from .perceive import perceive
from .plan_episode import plan_episode
from .review_and_judge import review_and_judge


def compile_episode_graph() -> CompiledStateGraph:
    """把 5 个格装配成图，返回编译好的对象。

    **一个分叉**：`review_and_judge` 出口的 `done` 决定进收尾还是继续循环。
    `act` 出口无条件回 `perceive`（每个 task 的结算都要先吸收、再判停）；
    队列还有没有 task 由 `plan_episode` 自己看。

    **书写纪律**：`add_node` 逐行写字面量——顶层即流程，"节点集"能被 `ast`
    机械读出来。
    """
    # ========== 1. 注册 5 个格 ==========
    graph = StateGraph(EpisodeRunState, context_schema=EpisodeRuntime)
    graph.add_node("perceive", perceive)
    graph.add_node("review_and_judge", review_and_judge)
    graph.add_node("plan_episode", plan_episode)
    graph.add_node("act", act)
    graph.add_node("episode_done", episode_done)

    # ========== 2. 接边——判停出口按 done 分叉，act 出口无条件回 perceive ==========
    graph.set_entry_point("perceive")
    graph.add_edge("perceive", "review_and_judge")
    graph.add_conditional_edges(
        "review_and_judge",
        lambda state: "episode_done" if state.done else "plan_episode",
        {
            "plan_episode": "plan_episode",
            "episode_done": "episode_done",
        },
    )
    graph.add_edge("plan_episode", "act")
    graph.add_edge("act", "perceive")
    graph.add_edge("episode_done", END)
    return graph.compile()


__all__ = [
    "compile_episode_graph",
]
