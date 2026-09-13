"""实验旋钮：全项目**唯一的策略常量**集中地。

**这里放什么**：调一个数就改变 agent 行为的那些旋钮——重试预算、输出上限、
召回条数、停滞判定阈值。它们的共同特征是**属于实验变量**：调小是为了控成本/控延迟，
调大是为了给模型更多空间。改这里不需要动任何逻辑。

**这里不放什么**：模块私有的物理/协议常量。比如 `world/pyboy_world.py` 的
`PRESS_FRAMES`（按键按住多少帧）、`world/ram.py` 的内存地址表、
`brain/providers.py` 的 `IMAGE_TOKEN_FLOOR`、`memory/store.py` 的
记录种类集合。它们不是"实验旋钮"而是**该模块实现的一部分**，换个世界/换个网关
就换掉了，搬进来反而割裂。判据：**改这个数是为了做实验还是为了让代码正确？**
前者来 config，后者留原地。

**为什么不放 harness**：这些旋钮的消费者跨三层——`tools/brain_tool.py` 校验动作、
`tools/prompts/*` 渲染上限、`harness/episode/**` 判定停滞、`harness/run/**` 控制重试。
常量住在任何一个消费方里，其余两方就得反向 import 那个层，依赖方向立刻破。
放顶层则谁都只依赖 config，方向永远向下。

**为什么不读环境变量**：env 是**部署配置**（端口、超时、开关），改它是因为机器/服务变了；
这里是**实验配置**，改它是因为这一轮实验想试别的参数。两者生命周期不同，混在一起
会让"这次实验的配置"无法从代码里复现。env 读取留在各自模块（如 `api.py`）。
"""

from __future__ import annotations

# ---- 重试预算：一次调用最多问几遍外部模型 ----
# brain 的六条链路（choose/plan/judge/verify/summarize 调模型，reflect 不调）
# 在 `tools/brain_tool.py` 里走**同一个**重试循环，预算就是下面这一个数。
# 感知（world）另有自己的预算——它是另一条链路、另一个重试循环。

BRAIN_MAX_ATTEMPTS = 3
"""brain 各链路的重试预算：一次调用最多问几遍模型（含首次）。

**为什么五条链路共用一个数**：它们的失败形态是同一个（模型调不通 / 输出解析
不出），而"要不要再问一次"的答案在同一层（tool）——分开配只会让人以为它们
可以独立调，实际上没有证据支持任何一个链路该多试或少试。
真需要分化时再加字段，那时也有数据支撑。

`decide_action` 的重试会**叠加纠正说明**（每次把上次错在哪拼进 prompt），
所以它那条链路的重试携带信息增量；其余四条是**原样重问**。
"""

PERCEPTION_MAX_RETRIES = 2
"""视觉感知重试预算：一帧最多读几次。world 侧的循环用它。"""

MAX_GOAL_RETRIES = 2
"""同一个目标最多自动重试几次（不含首次派发）——即最多被派发
`1 + MAX_GOAL_RETRIES` 次。耗尽后 `reflect` 强制弹出该目标、交人工处置；
没有这条硬上限，"失败保留栈顶 + 自动继续的 reviewer"就是一个死循环。"""


# ---- 动作输出上限：模型一次决策能写多大 ----
# **两个消费者必须同源**：prompt 渲染与 tool 校验读同一份，
# 不会出现"prompt 说 4 段、校验说 3 段"的自相矛盾。

MAX_RATIONALE = 2
"""**一段**动作最多带几条论据。

论据的粒度是"段"而非"整条链"，所以总量是"段数 × 条数"。段是单一意图，
通常一条依据就够，第二条的位置留给"确实还有一条独立依据"。
"""

MAX_SEGMENTS = 4
"""一条链最多几段。

不设上限时模型可以写几十段，一次决策吃光整局的步数预算；中途撞墙时还要把没按的键
整段作废。4 段足够表达"拐几个弯、末尾按一下"。
"""

MAX_TIMES = 8
"""一段最多连按几次。

模型会写 `"times": "100"`。连按期间 agent 看不见中间状态，撞墙了也会把剩下几次按完
——这是时序抽象的经典取舍。收益是**省感知调用**：走 5 格从 5 次 VLM 调用变成 1 次，
而感知是每步都花钱的那一项。
"""


# ---- 循环控制：一局/一轮允许跑多久 ----

STALL_LIMIT = 5
"""L2 护栏：连续多少步"动作与画面机械状态都没有变化"就强制结束本局。

阈值取 5：一两次重复可能是模型没看清，连续五次原地打转才断定它陷入循环。
它上面还有更硬的一层——run 级 `MAX_GOAL_RETRIES`，本局结束不是终点。
**两个读者**：`episode/gate/judge.py`（判停）与 `episode/close/close_episode.py`
（记 `stalled`）；算 `stall_count` 的 `press/detect_stall.py` 反而**不读它**——
算数与判断分离，阈值多少跟算数那一格无关。
"""

MAX_PLAN_PUSH = 5
"""一次 run 最多往目标栈里压几个目标——防止 planning 无限膨胀。"""

NODES_PER_DECISION = 10
"""一次决策在**链首**烧掉的节点数：

    save_checkpoint → record_observation → judge → get_action_space
    → 四路 retrieve → merge_retrieval → think_action

`save_checkpoint` 现在是**空转 stub**（存档链已删，见 `CHANGELOG.md`），但它
仍占图上的一格、每个链首仍多走一个 superstep——所以计数不变。
"""

NODES_PER_PRESS = 7
"""链内**每按一个键**走完一圈的节点数：

    act → perceive_after_action → apply_stop → detect_stall
    → store_step_episode_memory → store_object_semantic_memory → close_step

`close_step` 出口的分叉（回 `act` / 回 `save_checkpoint`）两条路都算得进来：
队列空时下一圈从 `save_checkpoint` 起头，那一圈的开销由 `NODES_PER_DECISION` 出。
"""

RECURSION_MARGIN = 20
"""图引擎自身开销 + 收尾分支（最多 5 个节点）的余量。"""

RUN_RECURSION_LIMIT = 200_000
"""run 图的 superstep 闸门——**一个大数，不是预算**。

run 图只有 6 格（`begin` / `plan` / `dispatch` / `episode` / `reflect` / `review`），
每轮派发烧掉个位数 superstep——它该跑多少**没有业务语义可算**，也不必算：真正贴身的
限在内层，`episode_entry.episode_budget()` 按"剩余步数 × 17 + 20"**逐局**算，那才是
"这一局能不能跑完"的守护。

所以这里只留一个**可调的闸门**，唯一用途是"run 图万一不收敛时，别让进程无限跑下去"。
想收紧失控时长（少烧几次 `plan` 的模型调用）就调小，想放宽就调大——**run 级一个大数、
episode 级一个按局算的数**，两层各留一个能改的常量。

**历史：为什么不再是一项公式。** 它曾是三项之和（run 自己的节点 + Σ episode 内部步数
+ `MAX_PLAN_PUSH` 给的压栈余量），那是 **F5**"子图步数计入父 limit"时代的产物。
**探针 X5** 实测本仓是**形态 B**（`run/nodes/episode.py` 调 `episode_entry.run_new`，
由后者 `graph.invoke` 起子图——父子各算各的计数：父 limit=3 时子图照跑完），
Σ 那一笔是**纯余量**——留着它只会把闸门抬到 20 万量级，却对"run 图失控"毫无守护作用。
拍板结果是把那个量级**显式写成一个常量**。几个候选的对照见 `CHANGELOG.md` (33)。
"""


# ---- 召回与判定：一次读多少、看多远 ----

MEMORY_RECALL_LIMIT = 5
"""每次知识库检索取几条。

**两个读者**：每步的 `retrieve_knowledge_semantic_memory` 与收尾的
`close/retrieve_verify_knowledge`——同一次"知识库召回上限"在两处落地，
共用一个数字，改一处就够。两个读者正是它该住 config 的判据。
"""

EPISODE_MEMORY_RECALL_LIMIT = 3
"""每次决策检索几条跨局摘要记忆。"""

JUDGE_DECISION_HISTORY = 2
"""`judge` 判定时能看到的本局最近几条**链**（`render(reason=False)`，不含决策者主张）。

**单位是决策，不是步**：一次决策 = 一串键，所以"最近 2 次决策"就是换粒度之前的
"最近 2 步"。粒度下沉到单键之后若还按步取，判定器的时间视野会被**静默除以决策长度**
（一次决策能按 8 键），而它判的"事件"类判据前提就是"证据可能在前几次决策的快照里"
——所以换的是**单位**，数字 2 没动。窗口大小的取舍（含已知风险）见 `CHANGELOG.md`
2026-09-05 条目。
"""

JUDGE_HISTORY_KEY_CAP = 8
"""上面那个窗口一次**最多取几个键**（查询上限，也是渲染上限）。

**为什么要有帽**：链长没有上限（`MAX_SEGMENTS × MAX_TIMES` = 32 键），两条长链能把
判定器的 prompt 顶到十几条记忆。8 = 一条打满 `MAX_TIMES` 的单段链：实测一条记忆
渲成文本约 490 字符、判定 prompt 本体约 4 千字符，8 条就是它的量级上限。真机实测
`press_count` 全是 1，这个帽现在根本碰不到——它防的是链一长就静默膨胀。
"""
