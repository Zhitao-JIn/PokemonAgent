"""run 图的装配：5 个节点 + 3 条条件边 + 挂在 `episode` 那格上的 `error_handler`。

拓扑（**0914 控制台改造：`reflect` 已删，其活并入 `review`**）：

    begin ──→ plan ──→ dispatch ──→ episode ──→ review ──→ plan
              │  ↑                                        │
              │  └────────────────────────────────────────┘
              └─(done)→ END

- `plan` 出口：`done` → `END`；否则 → `dispatch`（见表末检，`nodes/plan.py`）。
- `review` 出口只有一条：→ `plan`。

**`review` 是新的汇合点**：它同时干四件事——收结算（原 `reflect`）、盖章改状态
（原 `reflect` 的弹栈）、亮给人审、给这一局补记忆章（0914 S3：异常局在
`episode_memory` 里零痕迹，那里是唯一的收口）。所以 `episode` 与
`episode_error_handler` 都指向它。

**`review → plan`、绝不 `review → dispatch`**（`docs/PLAN_console_reviewer.md` §3.1/§3.3）：
失败目标会被盖章成 **`FAILED`（终态、不自动重派）**，"要不要再开一局"必须由 `plan`
读表后表态——`Planner` 显式把那条 `FAILED` 重开成 `PENDING`，出口才会再派。
那是"重试是 plan 的决策，不是自动动作"这句定调的字面落地。若直接回 `dispatch`，
就等于绕过 `plan` 把重试变回自动的，与整个方案的前提冲突。
（**失败若置回 `PENDING`，"无活跃条目 + planner 不新增"这条表末检永远不成立**，
`review → plan → dispatch` 会无限派发——`tests/test_run_graph_termination.py`
钉的就是这一处，别照着旧注释改回去。）

**`done` 由 `plan` 写、不是 `review` 写**：§3.3 示意图里写"`done` 由 review 写"，
但那与 §4.3 的判据冲突——判据是「表里没有任何 `PENDING`/`RUNNING` 条目 **且**
`Planner` 不新增」，而"`Planner` 这一版新增了吗"只有调过它的 `plan` 知道。
所以实现以 §4.3 的判据为准，`done` 的写入点在 `nodes/plan.py`。

> **`review → plan → review` 为什么不会转圈**：`plan` 在"表里没有活跃条目 +
> `Planner` 不新增"时判 `done` → `END`。那条表末检就是这张图能停机的前提，
> 改动它前先回 `nodes/plan.py` 读那段注释。

**`episode` 是"两张图怎么连"的落点**：
`dispatch` 退成**纯前置**（选目标、盖 RUNNING、生成 `episode_id`、把父侧的 `task` /
`episode_goals` 写进 state），派发本身由 `episode` 节点做。

- `error_handler` 挂在这一格上（F4 实测：handler 拿到的是**父 state**，返回
  `Command(goto="review", update=…)` 时流程正常继续）——这就是原先 `dispatch` 里
  那句 `except AgentError` 的官方落点，"单局异常不崩掉整个 run" 的契约没有丢。
- 子图步数**是否**计入父 limit：F5 说"计"，但那只对形态 A（子图当 `add_node` 的函数直挂）
  成立；本仓是形态 B（节点里 `graph.invoke`），探针 X5 实测父子各算各的。所以 run 级
  不再去算 episode 那一笔——只给一个可调的**闸门常量**
  （`pokemon_agent/config.py` 的 `RUN_RECURSION_LIMIT`），
  贴身的限归内层 `episode_entry.episode_budget()`。

**本模块是"只有 import 与装配"**：5 个节点各自住在 `nodes/<节点名>.py`
（命名规则 §5.3-⑤：节点文件名 = 这里 `add_node` 的字面量），本模块只负责
"把哪些节点按什么顺序接起来"。

`add_node` **逐行写字面量**：顶层即流程，且"每个节点名恰好一个实现文件"靠
`ast` 抽这些字面量做机械核对。
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ..deps import HarnessDeps
from .nodes.begin import begin
from .nodes.dispatch import dispatch, episode_error_handler
from .nodes.episode import episode
from .nodes.plan import plan
from .nodes.review import review
from .run_state import RunState


def compile_run_graph() -> CompiledStateGraph:
    """把 5 个节点与它们之间的边装配成图，返回编译好的对象。

    **不带参数**：节点名 → 节点函数那张表就是 `nodes/` 下的 5 个模块，
    本模块 import 它们即可——装配与实现分居两层，一张表两处维护的窗口关掉了。

    `episode_error_handler` 是本图唯一一个"只在出错时才跑"的节点——它不当顶点用，
    只交给 `add_node(..., error_handler=)`（F4）。

    `START` 直接进 `begin`——**恢复分流已随 checkpoint 恢复链删除**（原先它按
    `resume_episode` 决定跳过 `begin`/`plan` 直进 `dispatch`；见 `CHANGELOG.md`
    2026-09-13 第 57 条）。

    **`context_schema` 声明成 `HarnessDeps`**（全图唯一的 context，F10）：
    `run_entry.new_run()` 用 `invoke(..., context=deps)` 递进来，episode 那只子图
    通过它拿到同一份依赖与账。类型参数只能填它。
    """
    graph = StateGraph(RunState, context_schema=HarnessDeps)
    graph.add_node("begin", begin)
    graph.add_node("plan", plan)
    graph.add_node("dispatch", dispatch)
    # `episode`：派发这一局（内部是 episode 那只子图），异常由 handler 兜成失败结算。
    graph.add_node("episode", episode, error_handler=episode_error_handler)
    graph.add_node("review", review)
    graph.add_edge(START, "begin")
    graph.add_edge("begin", "plan")
    # `plan` 出口两路：done → END；否则必是"表里有待派目标" → dispatch。
    #
    # **没有第三条边**（`PLAN_console_reviewer.md` §3.3 的示意图里画过一条
    # "表非空但没 PENDING → review 再看一眼"，这里不实现它）：那条路在本图的
    # 可达状态里**不存在**。`plan` 的来路只有两条——首轮 `begin`（全 `PENDING`）
    # 或 `review`（刚把那条 `RUNNING` 盖章清掉），所以进来时表里要么没活跃条目、
    # 要么全是 `PENDING`。前者被 `plan` 的表末检判成 `done`（→ END），后者走到
    # 这里就是 `_has_pending` → `dispatch`。留一条永远走不到的边只会让读图的人
    # 以为存在那种状态，所以它被删了。
    graph.add_conditional_edges(
        "plan",
        lambda s: END if s.done else "dispatch",
        {"dispatch": "dispatch", END: END},
    )
    graph.add_edge("dispatch", "episode")
    graph.add_edge("episode", "review")
    # `review` 出口**只有一条**：回 `plan`。刻意不走 `dispatch`——"要不要再派一局"
    # 是 plan 读表后的决策（§3.1"重试是 plan 的决策，不是自动动作"），不是自动重试。
    # 注意：`done` 由 `plan` 写、不是 `review` 写（§3.3 那句"done 由 review 写"
    # 与 §4.3 的判据冲突——判据要问"Planner 这一版新增了吗"，那只有 `plan` 知道）。
    graph.add_edge("review", "plan")
    return graph.compile()


__all__ = ["compile_run_graph"]
