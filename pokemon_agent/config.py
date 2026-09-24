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
会让"这次实验的配置"无法从代码里复现。env 读取留在各自模块
（`brain/providers.py` 读密钥、`experiment/real_check/common.py` 读核对参数）。
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

`decide_action` 的重试**只在解析类失败时叠加纠正说明**（把上次错在哪拼进
prompt，0915 起按 `error_kind` 分叉）；传输失败（`ToolTimeout`）是**原样重问**
——模型根本没收到题，没有什么可"纠正"的；4xx（`ProviderRejected`）**不重试**。
"""

PERCEPTION_MAX_RETRIES = 3
"""视觉感知重试预算：一帧最多读几次。world 侧的循环用它。

0915 起 2→3：provider 层的重试同日删掉，感知这条链的总尝试次数原为
provider 3 × 循环 2 = 6，砍完只剩循环自己——而它扛的恰好是"带图的大请求"
（跨境 TLS 断连高发，见 `providers._post` docstring），提到 3 对齐 brain 的预算。
"""

PROVIDER_JSON_MODE = True
"""**要不要让服务端约束输出为合法 JSON**（请求体带 `response_format: json_object`）。

**它是实验旋钮**：五个位置（decide / judge / verify / plan 四条文本链 + world 感知）
的每一次请求都输出一个 JSON 对象，所以统一开关，装配时递给全部 provider。
打开的前提与已知风险见 `brain/providers.py::_OpenAICompatibleBase.__init__`
（prompt 含 `json` 字样与样例、服务端可能返回空 content、图片请求与 Qwen / Ark
是否接受该字段尚未验证）。关掉 = 回到"靠 prompt 要求 + 本地解析兜底"。
"""

PLAN_THINKING = True
"""`plan` 位置（run 级规划 `plan()` 与 episode 级拆解 `decompose()` 共用的那个 provider）
要不要开**思考模式**。

**它是实验旋钮**：这两条链路要在地图、目标表上做空间与依赖推理，关思考时模型只能一口气
写出答案（真机第一跑：拆解出了目标格是墙的 task）。开了会更慢更贵——思考 token 计入
`reasoning_tokens`，单请求超时随之放宽（`brain/build_llm_providers.py::THINKING_TIMEOUT_SECONDS`）。
只影响 `plan` 位置；decide / judge / verify / 感知仍关思考。关掉 = 回到从前。
"""

MODEL_RETRY_BACKOFF_SECONDS = 0.5
"""两个重试循环（`brain_tool` / `game_tools`）失败后到下一次尝试的**固定**间隔。

只对"值得重试"的失败生效（`ProviderRejected` 快败不睡）；最后一轮失败后
不睡——后面是上抛，没人等这个间隔。不用指数退避（0915 用户定）：重试预算
一共 3 轮，0.5/1/2s 的拉开收益兜不住多写的两行。"""

CONSOLE_REVIEW_TIMEOUT = 30.0
"""控制台提问的等待秒数——超时按"人没意见"处理。

**两个消费者**（同一个数，两种机制）：`ConsoleReviewer.inject()`（插话：超时→空串，
即不重问）与 `ConsoleReviewer.audit()`（审：超时→认账）。
取 30 秒：够人看清一屏上下文并打字，又不至于让无人值守的 run 每步白等。
**它取代了旧的 `MAX_GOAL_RETRIES`**——那条硬上限删掉后，"重试几次"改由 plan
读历史后决策（见 `docs/PLAN_console_reviewer.md` §3.1），run 级不再有自动重试预算。
"""


# ---- 动作输出上限：模型一次决策能写多大 ----
# **两个消费者必须同源**：prompt 渲染与 tool 校验读同一份，
# 不会出现"prompt 说 4 段、校验说 3 段"的自相矛盾。

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

ACT_STALL_LIMIT = 5
"""task 层停摆上限：连续多少**键**"动作与画面机械状态都没有变化"就结束本 task。

三层各自独立计数、各有一道停摆上限：task 数键（本常量）、episode 数连续失败 task
（`EPISODE_STALL_LIMIT`）、run 数连续失败局（`RUN_STALL_LIMIT`）。读者都是本层的
`review_and_judge`；算 `stall_count` 的单元不读它。
"""

EPISODE_STALL_LIMIT = 3
"""episode 层停摆上限：连续多少个 task 失败就结束本局。"""

RUN_STALL_LIMIT = 3
"""run 层停摆上限：连续多少局失败就结束本 run。"""

RUN_MAX_EPISODES = 50
"""run 层预算：一个 run 最多派多少局（episode 与 task 的预算各在自己的 `Task.max_steps`）。"""

EPISODE_MAX_TASKS_PER_PLAN = 5
"""一次拆解最多**建议**模型给几个 task（给模型的上限，harness 不截断）。"""

PLAN_MAX_NEW_GOALS = 3
"""一次规划最多**建议**模型给几个新目标。

**这是给模型的建议上限，不是截断**（0914 S2，取代旧的 `MAX_PLAN_PUSH`）：
旧常量是 plan 节点的硬护栏——模型给多了就裁掉，而裁剪就是**静默丢目标**。
现在目标表的增长由 planner 自己负责，`plan` 节点不替它裁；这个数只渲进
`run_plan.md` 的"一次最多给 $max_push 个"，是个提示。

取 3：规划是"拆下一步"，一次能想清楚并写对 3 条以上递进目标的场合很少；
写多了质量反而降（模型会把同一条拆成几个近义目标凑数）。"""

NODES_PER_DECISION = 3
"""一圈决策烧掉的节点数：`perceive → review_and_judge → plan_*`（组合格只算一格）。"""

NODES_PER_PRESS = 1
"""一圈执行烧掉的节点数：`act`（task 层只按键；episode 层派一个 task）。"""

RECURSION_MARGIN = 20
"""图引擎自身开销 + 收尾分支（最多 5 个节点）的余量。"""

EPISODE_RECURSION_LIMIT = 20_000
"""episode 图的 superstep 闸门——**大数，不是预算**（0923 188）。

episode 一圈 = 一个 task（`act` 派发、task 子图内部自管键级循环），一局的圈数
没有可算的业务上界，所以本层不再按步数换算，只防"不收敛"；**键级预算的贴身限
在 task 层**（`task_entry.task_budget`）。同 `RUN_RECURSION_LIMIT` 一条逻辑：
想收紧失控时长就调小，想放宽就调大。
"""

RUN_RECURSION_LIMIT = 200_000
"""run 图的 superstep 闸门——**一个大数，不是预算**。

run 图只有 6 格（`begin` / `perceive` / `review_and_judge` / `plan_run` / `act` /
`run_done`），每轮派发烧掉个位数 superstep——它该跑多少**没有业务语义可算**，也不必算：
真正贴身的限在 task 层（`task_entry.task_budget()` 按"键预算 × 每键格数"算），
episode 层用 `EPISODE_RECURSION_LIMIT` 大数兜底。

所以这里只留一个**可调的闸门**，唯一用途是"run 图万一不收敛时，别让进程无限跑下去"。
想收紧失控时长（少烧几次 `plan` 的模型调用）就调小，想放宽就调大——**run 级一个大数、
episode 级一个按局算的数**，两层各留一个能改的常量。

**历史：为什么不再是一项公式。** 它曾是三项之和（run 自己的节点 + Σ episode 内部步数
+ `MAX_PLAN_PUSH` 给的压栈余量），那是 **F5**"子图步数计入父 limit"时代的产物。
**探针 X5** 实测本仓是**形态 B**（run 图的 `act` 格调 `episode_entry.run_episode`，
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

CHOOSE_HISTORY_STEPS = 8
"""`plan_task` 决策时带上本 task 最近几条 ActMemory（`task_ctx.act_memories` 的尾部）。

只取**本 task** 的：前面几个 task 的经验已由 episode 层消化进 TaskMemory，不越层。
"""

JUDGE_HISTORY_STEPS = 3
"""task 层 `judge` 判定时能看到的本 task 最近几条 ActMemory（`render(reason=False)`，
不含决策者主张）。

**单位是 step memory 条数，按条取，不按决策分组。** 一次决策展开成 L 个键就是
L 条 step memory，取"最近 3 条"就是字面意思——不再乘 L。

**为什么改回条数**（2026-09-14 定案）：0913 粒度下沉（步 → 键）时，这个窗口曾被
换算成"最近 2 次决策"，理由是"保持时间视野不被静默除以决策长度"。但那个换算把
**窗口大小**和**单位**绑在了一起——判定器要看的是"最近发生了什么"这个**事件窗口**，
事件就是逐个键发生的，窗口本来就该按事件条数说。按决策取的结果是窗口随 L 浮动
（L=1 取 2 条、L=4 取 8 条），同一句"最近 2 次"在不同链长下看到的事件量差 4 倍，
判据前提反而不可控。改回条数后窗口恒定，链长怎么变都不影响判定器的证据量。
"""

# 历史：`JUDGE_HISTORY_KEY_CAP = 8` 已删（2026-09-14）。
# 它原本是"按决策取窗口"的配套查询上限（防两条长链把 prompt 顶爆）。改成按条数
# 取之后，`JUDGE_HISTORY_STEPS` 本身就是条数上限，查询上限与渲染上限同源，
# 再留一个帽就是两个数字描述同一件事、还能互相矛盾（cap < steps 时截断静默发生）。
# 链长膨胀的风险也一并消除：取的是固定 3 条，与 L 无关。
