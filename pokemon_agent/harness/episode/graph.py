"""episode 图：一局的 21 个节点按 7 个功能域展开。

**步 0 的形态**：节点还是 `EpisodeHarness` 的方法（`nodes[...]` 里传进来），
本模块只负责"把哪些节点按什么顺序接起来"——**图长什么样**与**节点怎么实现**
从这一步起分居两个文件。步 3 再把节点逐个搬成自由函数、按域分文件夹（见
`PLAN_graph_composition.md` §3.1/§6）。

`compile_episode_graph()` 的 `add_node` **逐行写字面量**（不用循环）：
顶层即流程，一眼看出这张图有哪些节点、按什么顺序；`scripts/check_graph_phases.py`
正是 `ast` 抽这些字面量与观测台的相位表逐条比对。

**三个节点数常量住这里**（步 2 从 `episode_harness.py` 搬来）：它们算的是
`recursion_limit`，而 limit 是"这张图长什么样"的函数——跟 `add_node` 的字面量
放在一起，改节点集时改一处就够。内层的 limit 由 `entry.episode_budget()` 用，
外层的总预算由 `run_harness.py` 用（D6：两处必须同一条公式）。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ..deps import HarnessDeps
from .state import EpisodeRunState

NodeFn = Callable[[EpisodeRunState], dict]
"""一个节点的形状：读 state 全量，只回**状态增量**。"""

NODES_PER_DECISION = 10
"""一次决策在**链首**烧掉的节点数：

    save_checkpoint → record_observation → judge → get_action_space
    → 四路 retrieve → merge_retrieval → think_action
"""

NODES_PER_PRESS = 7
"""链内**每按一个键**走完一圈的节点数：

    act → perceive_after_action → apply_stop → detect_stall
    → store_step_episode_memory → store_object_semantic_memory → close_step

`close_step` 出口的分叉（回 `act` / 回 `save_checkpoint`）两条路都算得进来：
队列空时下一圈从 `save_checkpoint` 起头，那一圈的开销由 `NODES_PER_DECISION`
出。"""

RECURSION_MARGIN = 20
"""图引擎自身开销 + 收尾分支（最多 5 个节点）的余量。"""


def compile_episode_graph(nodes: Mapping[str, NodeFn]) -> CompiledStateGraph:
    """把 21 个节点与它们之间的边装配成图，返回编译好的对象。

    `nodes` 的键就是节点名（与 `add_node` 的字面量逐字相同），值是节点函数。

    **两个出口分叉**：`judge` 出口的 done 分支决定进收尾链还是继续循环；
    `close_step` 出口按 `pending_presses` 是否为空决定回 `act`（链还没按完）
    还是回 `save_checkpoint`（该重新决策了）。后一条就是"链内小循环"，它只加
    一条边、不加节点。

    `save_checkpoint` 因此是**链边界**（不是每一步的边界）：每一条链的首
    （含 step0）都在同一节点写 checkpoint（PLAN_checkpoint §2）——每键一份含
    模拟器快照的存档会让存档量乘上链长，而链内执行是纯 RAM 确定的，从链首存档
    重放能逐帧复现，链内不必存。

    终止分支在 `judge` 出口——四类终止来源（世界结束/步数用尽/停摆/目标
    达成）全在 `judge` 一格里判完，`record_observation` 只记账，不掺和
    "该不该停"。

    四个 `retrieve_*` 节点按边排成一条直线（图引擎要求边有先后），但彼此
    没有数据依赖——都只读 `observation`，各写各的字段，顺序是图形状要求
    的，不是因果依赖。

    **收尾链的每一条分支都汇到 `close_episode`**（D2-④）：没有 step 记忆时
    `retrieve_verify_step_memory` 直接跳它，有记忆时 `verify_and_summarize` 接它
    ——两条路都要经过它，因为"本局结算（`outcome`）"必须由子图自己写出，
    否则父侧读到的是上一轮的陈旧值（F1 的反作用，且不报错）。

    **`context_schema` 声明成 `HarnessDeps`（步 2）**：F10 实测子图的这句声明
    **不被校验**（穿过去的永远是父图那个对象）——所以这里声明成**同一个类型**
    是唯一诚实的选择：声明成别的会变成一颗静默地雷。写下来也给
    `scripts/check_graph_phases.py` 一条可机械核对的依据（`Runtime[...]` 的
    类型参数只能是它）。
    """
    # 步骤 1：注册 21 个节点——书写顺序 = 执行顺序。
    graph = StateGraph(EpisodeRunState, context_schema=HarnessDeps)
    graph.add_node("save_checkpoint", nodes["save_checkpoint"])
    graph.add_node("record_observation", nodes["record_observation"])
    graph.add_node("judge", nodes["judge"])
    graph.add_node("get_action_space", nodes["get_action_space"])
    graph.add_node("retrieve_step_episode_memory", nodes["retrieve_step_episode_memory"])
    graph.add_node("retrieve_global_episode_memory", nodes["retrieve_global_episode_memory"])
    graph.add_node(
        "retrieve_knowledge_semantic_memory", nodes["retrieve_knowledge_semantic_memory"]
    )
    graph.add_node("retrieve_object_semantic_memory", nodes["retrieve_object_semantic_memory"])
    graph.add_node("merge_retrieval", nodes["merge_retrieval"])
    graph.add_node("think_action", nodes["think_action"])
    graph.add_node("act", nodes["act"])
    graph.add_node("perceive_after_action", nodes["perceive_after_action"])
    graph.add_node("apply_stop", nodes["apply_stop"])
    graph.add_node("detect_stall", nodes["detect_stall"])
    graph.add_node("store_step_episode_memory", nodes["store_step_episode_memory"])
    graph.add_node("store_object_semantic_memory", nodes["store_object_semantic_memory"])
    graph.add_node("close_step", nodes["close_step"])
    graph.add_node("retrieve_verify_step_memory", nodes["retrieve_verify_step_memory"])
    graph.add_node("retrieve_verify_knowledge", nodes["retrieve_verify_knowledge"])
    graph.add_node("verify_and_summarize", nodes["verify_and_summarize"])
    graph.add_node("close_episode", nodes["close_episode"])

    # 步骤 2：接边——judge 出口按 done 分叉，其余是直线。
    graph.set_entry_point("save_checkpoint")
    graph.add_edge("save_checkpoint", "record_observation")
    graph.add_edge("record_observation", "judge")
    graph.add_conditional_edges(
        "judge",
        lambda state: "retrieve_verify_step_memory" if state.done else "get_action_space",
        {
            "get_action_space": "get_action_space",
            "retrieve_verify_step_memory": "retrieve_verify_step_memory",
        },
    )
    graph.add_edge("get_action_space", "retrieve_step_episode_memory")
    graph.add_edge("retrieve_step_episode_memory", "retrieve_global_episode_memory")
    graph.add_edge("retrieve_global_episode_memory", "retrieve_knowledge_semantic_memory")
    graph.add_edge("retrieve_knowledge_semantic_memory", "retrieve_object_semantic_memory")
    graph.add_edge("retrieve_object_semantic_memory", "merge_retrieval")
    graph.add_edge("merge_retrieval", "think_action")
    graph.add_edge("think_action", "act")
    graph.add_edge("act", "perceive_after_action")
    graph.add_edge("perceive_after_action", "apply_stop")
    graph.add_edge("apply_stop", "detect_stall")
    graph.add_edge("detect_stall", "store_step_episode_memory")
    graph.add_edge("store_step_episode_memory", "store_object_semantic_memory")
    graph.add_edge("store_object_semantic_memory", "close_step")
    # 决策内小循环：队列还有键就回 `act` 再按一个（不再检索、不再决策），
    # 空了才回链首写 checkpoint / `record_observation` / `judge`。**这正是
    # "一次决策摊薄成 N 步"的落点**——决策调用与四路检索一回合一付，而
    # `detect_stall`/两个 store/`close_step` 每键各跑一次。分叉在 `close_step`
    # 出口而不是 `store_object` 出口：**扶正当前帧是"这一步关上"的一部分**，
    # 它必须发生在两个 store 读完 `before`/`after` 之后。
    graph.add_conditional_edges(
        "close_step",
        lambda s: "act" if s.pending_presses else "save_checkpoint",
        {"act": "act", "save_checkpoint": "save_checkpoint"},
    )
    # 收尾分支：没有 step 记忆（entries 为空）时直接进 `close_episode`——没有东西可
    # 校验/可蒸馏，不问模型（取舍见 `CHANGELOG.md` 2026-09-06 条目），但**结算照写**。
    graph.add_conditional_edges(
        "retrieve_verify_step_memory",
        lambda s: "retrieve_verify_knowledge" if s.verify_step_entries else "close_episode",
        {
            "retrieve_verify_knowledge": "retrieve_verify_knowledge",
            "close_episode": "close_episode",
        },
    )
    graph.add_edge("retrieve_verify_knowledge", "verify_and_summarize")
    graph.add_edge("verify_and_summarize", "close_episode")
    graph.add_edge("close_episode", END)
    return graph.compile()
