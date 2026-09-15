"""episode 图：一局的 21 个节点按 7 个功能域展开。

**步 3 起"图长什么样"与"节点怎么实现"分居两个文件**：本模块只负责"把哪些节点按什么
顺序接起来"——21 个节点全部从七个域包里 import，**节点文件名 = 这里 `add_node` 的字面量**
（此前那张 `nodes[...]` 传参表在步 3 收尾时去掉，因为域包本身就是节点表）。

`add_node` **逐行写字面量**（不用循环）：顶层即流程，一眼看出这张图有哪些节点、按什么
顺序，也让"节点集"这件事能被 `ast` 机械读出来。**曾经有一条
`scripts/check_graph_phases.py` 就是干这个的**——抽 `add_node` 的字面量、与观测台的
相位表逐条比对、核对"每个节点名恰好对应一个实现文件"；**它已不在仓库里**，那几条核对
现在没有可执行的守卫，只剩这条书写纪律（见 `docs/spec/harness/SPEC.md` 已知缺口）。

**三个节点数常量住这里**：它们算的是 `recursion_limit`，而 limit 是"这张图长什么样"的
函数——跟 `add_node` 的字面量放在一起，改节点集时改一处就够。内层的 limit 由
`entry.episode_budget()` 用，外层的总预算由 `run/run_entry.py` 用（D6：两处必须同一条公式）。

**`EpisodeInput` / `EpisodeOutput` 也住这里**（D2 的"交界契约"，产出地归档）：run 给这一局
什么、这一局还 run 什么，从散在代码里的约定变成两个**读得出来的模型**——"表里的每个键
都真的存在于两侧 state"这件事原先由 `scripts/check_graph_phases.py` 机械核对，**该脚本
已删**，现在只能人眼比（§5.3-②）。

**它们不进 `compile(input_schema=…/output_schema=…)`——步 4 的决定**：那两个参数是
**形态 A**（把编译好的子图直接当 `add_node` 的函数，父图按 schema 做键映射/裁剪）的机制；
本仓是**形态 B**（`run/nodes/episode.py` 那一格里 `graph.invoke(state, …, context=deps)`，交界由
`episode_entry` 的两个入口手工完成，探针 X5 已证父子各算各的）。接上去只会改变
`invoke` 的校验/裁剪行为（比如 `output_schema` 会把子图终态裁成只剩 `outcome`，
`episode_entry.close()` 那份完整 state 就没了），**收益为零、风险全在真机**。
所以这两个模型是**给人读、给脚本核**的契约，不是给图引擎的实参。
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

from pokemon_agent.brain import Goal, Task
from pokemon_agent.schemas.harness import FromRunHarnessToEpisodeHarnessRunResp

from ..deps import HarnessDeps
from .close import (
    close_episode,
    retrieve_verify_knowledge,
    retrieve_verify_step_memory,
    verify_and_summarize,
)
from .decide import think_action
from .episode_state import EpisodeRunState
from .gate import get_action_space, judge
from .open import record_observation, save_checkpoint
from .press import act, close_step, detect_stall, perceive_after_action
from .retrieve import (
    merge_retrieval,
    retrieve_global_episode_memory,
    retrieve_knowledge_semantic_memory,
    retrieve_object_semantic_memory,
    retrieve_step_episode_memory,
)
from .store import store_object_semantic_memory, store_step_episode_memory


class EpisodeInput(BaseModel):
    """**run 图交给这一局的键**——父子交界那张键表的上半张（D2）。

    三个键，逐字对应 `RunState` 里的同名键（F1：传递靠**键名交集**，没有别名机制）：

    | 键 | 父侧谁写 | 子侧谁读 |
    |---|---|---|
    | `episode_id` | `run/nodes/dispatch.py` | `episode_state.episode_id`（每个节点的账） |
    | `task` | `run/nodes/dispatch.py`（栈顶那层） | `episode_state.task`（`judge` 的判据） |
    | `episode_goals` | `run/nodes/dispatch.py`（整栈投影，D2-②） | `episode_state.episode_goals` |

    **它不是 `compile(input_schema=…)` 的实参**（步 4 的决定，理由见模块文档末段）：
    本仓是形态 B（节点里 `graph.invoke`），交界由 `episode/episode_entry.py` 的
    `run_new` 入口手工完成——这张表的价值在"读得出来 + 可机械核对"，不在于给图引擎看。
    """

    episode_id: str = Field(description="这一局的标识（`{run_id}-ep{n}`）")
    task: Task = Field(description="栈顶目标：这一局要解决的那一层")
    episode_goals: list[Goal] = Field(
        description="整个目标栈的投影（判只判栈顶 `episode_goals[-1]`）"
    )


class EpisodeOutput(BaseModel):
    """**这一局交回 run 图的键**——下半张（D2-④）。

    只有一个键：`outcome`（本局结算）。由 `close/close_episode.py` 写进子图 state，
    父图 `reflect` 读——**必须由子图自己写出**：F1 的反作用是"子图不输出的键，父侧
    保持旧值"，不写就会让 `reflect` 读到**上一次派发的陈旧结算**，而且不报错。
    """

    outcome: FromRunHarnessToEpisodeHarnessRunResp = Field(
        description="本局结算（失败/成功、步数、原因）——`reflect` 弹栈或重试的依据"
    )


def compile_episode_graph() -> CompiledStateGraph:
    """把 21 个节点与它们之间的边装配成图，返回编译好的对象。

    **两个出口分叉**：`judge` 出口的 done 分支决定进收尾链还是继续循环；
    `close_step` 出口按 `pending_presses` 是否为空决定回 `act`（链还没按完）
    还是回 `save_checkpoint`（该重新决策了）。后一条就是"链内小循环"，它只加
    一条边、不加节点。

    `save_checkpoint` 是**链边界**（不是每一步的边界）：每一条链的首（含 step0）
    都经过这一格。**存档实现已删、这一格现在空转**（保留位置与名字的理由见
    `open/save_checkpoint.py`）——但"链边界在这里"这个位置语义仍然成立：链内
    执行是纯 RAM 确定的，从链首能逐帧重放。

    终止分支在 `judge` 出口——四类终止来源（世界结束/步数用尽/停摆/目标
    达成）全在 `judge` 一格里判完，`record_observation` 只记账，不掺和
    "该不该停"。

    四个 `retrieve_*` 节点按边排成一条直线（图引擎要求边有先后），但彼此
    没有数据依赖——都只读 `observation`，各写各的字段，顺序是图形状要求
    的，不是因果依赖。

    **收尾链的每一条分支都汇到 `close_episode`**（D2-④）：没有 step 记忆时
    `retrieve_verify_step_memory` 直接跳它，有记忆时经 `verify_and_summarize`
    接它——两条路都要经过它，因为"本局结算（`outcome`）"必须由子图自己写出，
    否则父侧读到的是上一轮的陈旧值（F1 的反作用，且不报错）。

    **`extract_knowledge` 已摘出这张图**（0914 98）：它 0914 S4 曾是收尾链的
    第五格（`verify_and_summarize` 出口按 `verified_steps` 分叉出去抽世界知识），
    用户 0914 定「knowledge 由人管理」——节点不再跑，`verify_and_summarize`
    直接接 `close_episode`。**代码与账都没删**（`Brain.extract()` 第七链路 /
    prompt / `store_knowledge` 都在原位；`write_knowledge` 那本账已整账删除），
    **接回去只要三行**：这里 import + `add_node` + 把下面那条 `add_edge` 换回
    `add_conditional_edges`（形状见 `CHANGELOG.md` 第 98 条）。
    ⚠ 唯一悬空物：`state.verified_steps` 现在只有写方、没有读方——
    要么一起摘，要么接回去，别让它长期悬着。

    **`context_schema` 声明成 `HarnessDeps`**：F10 实测子图的这句声明
    **不被校验**（穿过去的永远是父图那个对象）——所以这里声明成**同一个类型**
    是唯一诚实的选择：声明成别的会变成一颗静默地雷。写下来同时也是一条可核对的
    依据（`Runtime[...]` 的类型参数只能是它）。
    """
    # 步骤 1：注册 21 个节点——书写顺序 = 执行顺序。
    graph = StateGraph(EpisodeRunState, context_schema=HarnessDeps)
    graph.add_node("save_checkpoint", save_checkpoint)
    graph.add_node("record_observation", record_observation)
    graph.add_node("judge", judge)
    graph.add_node("get_action_space", get_action_space)
    graph.add_node("retrieve_step_episode_memory", retrieve_step_episode_memory)
    graph.add_node("retrieve_global_episode_memory", retrieve_global_episode_memory)
    graph.add_node("retrieve_knowledge_semantic_memory", retrieve_knowledge_semantic_memory)
    graph.add_node("retrieve_object_semantic_memory", retrieve_object_semantic_memory)
    graph.add_node("merge_retrieval", merge_retrieval)
    graph.add_node("think_action", think_action)
    graph.add_node("act", act)
    graph.add_node("perceive_after_action", perceive_after_action)
    graph.add_node("detect_stall", detect_stall)
    graph.add_node("store_step_episode_memory", store_step_episode_memory)
    graph.add_node("store_object_semantic_memory", store_object_semantic_memory)
    graph.add_node("close_step", close_step)
    graph.add_node("retrieve_verify_step_memory", retrieve_verify_step_memory)
    graph.add_node("retrieve_verify_knowledge", retrieve_verify_knowledge)
    graph.add_node("verify_and_summarize", verify_and_summarize)
    graph.add_node("close_episode", close_episode)

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
    graph.add_edge("perceive_after_action", "detect_stall")
    graph.add_edge("detect_stall", "store_step_episode_memory")
    graph.add_edge("store_step_episode_memory", "store_object_semantic_memory")
    graph.add_edge("store_object_semantic_memory", "close_step")
    # 决策内小循环：队列还有键就回 `act` 再按一个（不再检索、不再决策），
    # 空了才回链首 `save_checkpoint` / `record_observation` / `judge`。**这正是
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
    # **这里原先是收尾链的第二个分叉**（0914 S4 → 98 摘除）：`verify_and_summarize`
    # 出口按 `verified_steps` 分叉，非空才去 `extract_knowledge` 抽世界知识。
    # 用户定「knowledge 由人管理」，那一格不再跑——**不抽知识成为唯一的路**，
    # 于是分叉退化成一条直边。接回去的形状见上面那条 docstring 与
    # `close/extract_knowledge.py`。
    graph.add_edge("verify_and_summarize", "close_episode")
    graph.add_edge("close_episode", END)
    return graph.compile()
