# Pokemon_Agent 项目规格说明

本文档是整个项目的入口索引。项目按模块（Python 包）组织，每个模块的详细规格
在它自己的子目录里（`schemas/SPEC.md`、`memory/SPEC.md` ……），本文件只给出
"整个项目怎么拼起来"这一层的说明——分层关系、数据怎么流动、跨模块的不变量。

## 项目是什么

一个用 LLM 玩《宝可梦 红》的 agent：真实 Game Boy 模拟器（PyBoy）+ 视觉模型读屏幕
+ 文本模型做决策 + 独立的判定模型判断目标是否达成。控制循环用 LangGraph 实现为
一张显式的状态图。核心设计主张贯穿全项目：**分层清楚、契约显式、trace 是唯一的
事实来源**——几乎每一次重构都是在修复"某个类知道了它不该知道的东西"这类耦合。

## 模块地图

```
pokemon_agent/
├── schemas/       跨层数据契约（Pydantic 模型）—— 大脑/工具/记忆/trace 之间传递的一切类型
├── memory/        语义记忆的纯存储层（不知道任何游戏规则）
├── tools/         Harness 伸向环境和记忆的两只手（GameTools / MemoryTool）
├── interfaces/    Protocol 定义（"港口"）—— 解耦 Harness 与具体实现
├── world/         WorldPort 的唯一实现：PyBoy + 视觉模型的粘合层
├── brain/         纯决策层：LLM 怎么变成一个合法的 Action
├── harness/       控制循环本体（LangGraph 状态图），全项目唯一写 trace 的地方
├── prompts/       所有 prompt 模板 + 组装辅助函数
├── providers/      具体的 LLM/视觉模型接入（DashScope/Qwen）
├── vision/        图像预处理（网格叠加等）
├── trace/         TracePort 的实现（store.py: LocalTrace，append/replay/sse；browser.py: 浏览器观测台）
│                  + 事件 payload 组装的纯函数（utils.py: trace_utils）
├── experiment/    实验 manifest（已接入 run_experiment.py）+ 任务定义 + 跑批入口
└── build.py       唯一的装配点（全项目唯一出现 `new` 具体实现的地方）

probe/             命令行脚本（跑真实 episode、调试工具）
```

各模块的详细规格：

- [`schemas/SPEC.md`](schemas/SPEC.md) —— 六个契约文件（task/observation/action/
  step_memory/object_fact/trace）的完整类型定义
- [`memory/SPEC.md`](memory/SPEC.md) —— 语义记忆存储层：三个协议 + 两个纯函数 +
  一个实现类
- [`tools/SPEC.md`](tools/SPEC.md) —— `GameTools`/`MemoryTool`：Harness 唯一认识的
  两个具体实现
- [`interfaces/SPEC.md`](interfaces/SPEC.md) —— 全部 Protocol 定义（六个文件）
- [`world/SPEC.md`](world/SPEC.md) —— `PyBoyWorld`：模拟器 + 视觉模型的粘合层
- [`brain/SPEC.md`](brain/SPEC.md) —— `Brain`：决策/反思/判定三个方法
- [`harness/SPEC.md`](harness/SPEC.md) —— 控制循环图，**项目里最核心的一份规格**
- [`prompts/SPEC.md`](prompts/SPEC.md) —— 九个 prompt 模板 + 加载/组装机制
- [`providers/SPEC.md`](providers/SPEC.md) —— DashScope/Qwen 接入 + 图像预处理
- [`build/SPEC.md`](build/SPEC.md) —— 装配、异常类型、`LocalTrace`/`trace_utils`、命令行入口

## 分层关系（谁认识谁）

```
probe/run_episode.py
        │  只 import build.py + errors + trace.store.LocalTrace
        ▼
build.py ── 全项目唯一一处具体类的 `new`
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│ Harness（harness/harness.py）                            │
│   持有: GameToolPort · MemoryToolPort · BrainPort · TracePort │
│   只认识这四个 Protocol，不认识任何具体实现                  │
└──────────┬───────────┬───────────┬───────────┬───────────┘
           │            │           │           │
     GameToolPort  MemoryToolPort BrainPort  TracePort
           │            │           │           │
      GameTools    MemoryTool     Brain       LocalTrace
      (tools/)      (tools/)    (brain/)      (trace/store.py)
                                            payload 组装另在
                                            trace/utils.py（不认识 TracePort）
           │            │           │
      WorldPort   SemanticObjectStore  LLMProvider ×2
           │            │        (decide_llm / judge_llm)
      PyBoyWorld    ObjectMemory       │
      (world/)      (memory/)      QwenText/QwenVision
           │                        (providers/)
      VisionProvider
           │
      QwenVision (providers/)
```

**Brain 不持有任何 tools/memory 引用**——`choose()` 把 `memories` 当参数收进来，
检索这件事是 Harness（具体说是图上的 `retrieve_memory` 节点）做的。这条约束是
这次会话里最后一轮重构定下的：以前大脑自己持有 `tools` 去调 `memory_query`，
"大脑自己决定检索什么"这件事看似合理，实际把决策层和检索策略耦在了一起。

**`GameToolPort`/`MemoryToolPort` 是两个不同的协议**，不是一个协议的两部分——
`Harness.__init__` 收两个独立参数 `game`/`memory`。以前是一个 `ToolHost`
（外加一个更小的、给大脑用的 `ToolPort`），感知世界和记忆混在同一个协议、
同一个实现类（`GameTools`）里；现在 `GameTools` 只碰 `WorldPort`，`MemoryTool`
只碰 `memory/` 包，两者互不相识，组合是 `Harness` 一个人的事。

## 一次决策循环怎么流动（跨模块视角）

这是把各模块的详细规格串起来看的"数据怎么流"版本，完整的图结构和事件时间线见
[`harness/SPEC.md`](harness/SPEC.md)：

1. **look**：`Harness._observe()` 调 `GameToolPort.perceive()` →
   一路调到 `PyBoyWorld._perceive()` → 触发 `VisionProvider.describe()`
   （除非命中帧哈希缓存）→ 解析成 `schemas/observation.py` 里的 `ScreenState`/
   `TerrainMap` → 组装成 `Observation`。`known_objects`/`knowledge` **不在这里拼**——
   `_observe()` 只产出这一帧实际看到的东西，语义记忆的读挪到下一步。
2. **retrieve_memory**：**四类记忆的读共用这一个图节点**——
   `query_episode_steps()` 取本局单步流水（全量、按 step 升序，
   `schemas/step_memory.py`）、`query_objects()` 拼进 `facts["known_objects"]`、
   `query_knowledge()`（混合检索）拼进 `facts["knowledge"]`、
   `query_episode_summaries()`（按场景 + 相关性）拼进 `facts["episode_memories"]`。
   判定（`_judge`）已经在上一步跑完，所以判定模型永远看不到这几个字段。
3. **think**：`Harness` 把 `goals`/`obs`/`space`/`memories` 交给
   `BrainPort.choose()` → `Brain` 用 `prompts/decide_action.md` 组装 prompt →
   调 `LLMProvider.complete()` → 解析成一个合法的 `Action`
   （`schemas/action.py`），失败则重试并把 `retry_note.md` 塞进下一次 prompt。
4. **press**：**这一版只有按键一类动作**，直接调 `GameToolPort.execute()` 推进世界。
   一步交出的是一条**按键链**（`Action.sequence`，多段链只能是 `up`/`down`），
   `execute()` 把整条链交给 `world.step()`，**世界只在链尾感知一次**——
   感知是每步都要付钱的那一项，`up×4` 拆成四次按键就是四次视觉调用。
   以前这里是 `press / push_goal / inspect` 三选一，按 `Action.intent` 在图上分派；
   拆子目标的机制要在别处重写，所以 `Intent` 连同分派一起删了（见
   [`harness/SPEC.md`](harness/SPEC.md) 3.1）。
5. **remember**（只在 press 之后）：`Harness` 调 `BrainPort.reflect()` 把
   前后两份 `Observation` 整理成一条 `StepMemory`，写回
   `MemoryToolPort.store_episode_step()`；再调
   `MemoryToolPort.store_objects_interactions()` 把这一步的语义记忆
   （门/招牌/人给出的信息）落进 `memory/` 包——**多段动作链和连按这一步不记**，
   因为链的两头之间路过了哪些格子看不到，记下来就是一条假的尝试记录。
6. **summarize**（只在终止那一轮）：`look` 判出 `done` 之后不进 `retrieve_memory`，
   改走 `summarize` —— 把这一局蒸馏成一条跨局摘要记忆（`EpisodeMemory`）。
   它**要调一次模型**，所以在图上占一格：图上看得见的东西才会被算进成本。
   随后图结束，`EPISODE_END` 由 `run()` 写下——正常结束和异常终止共用这一个出口。
7. 每一步产生的所有模型调用记录（`calls`，见下一节）和状态转移，最终都由
   `Harness` 一个人翻译成 `TracePort.append()` 事件——这是全项目唯一写
   trace 的地方（但组装 `payload` 这一步委托给 `trace/utils.py` 的纯函数，
   `Harness` 自己不拼 `dict` 字面量，见 `interfaces/SPEC.md` 第 4 节）。

## 贯穿全项目的几条不变量

这些是分散在各模块规格里、但只有放在一起看才成立的规则：

- **只有 Harness 写 trace。** 大脑、工具、世界都只把"发生了什么"
  （`ModelCall`、`Observation`、`ToolResult`）当返回值交出来，翻译成事件是
  Harness 一个人的工作。这条规则最近的体现：模型调用记账从
  `drain_calls()` + 内部缓冲区（生产者/消费者通过可变状态搭桥）改成了
  `calls` 直接跟着 `PerceptionResult`/`ToolResult` 返回值走——
  `reset`/`perceive`/`execute` 三个方法各自把这次调用产生的账单
  原样交出来，Harness 在 `_begin`/`_press`/`_observe` 里当场记账，
  不再有任何跨调用的隐藏状态。完整历史见 `interfaces/SPEC.md` 和
  `world/SPEC.md`。
- **`step` 只有一个主人。** `LoopState.step` 由 Harness 盖章，`Observation.step`
  在产出时是占位值（world 不知道自己在第几步）。这条规则是为了修一个真实
  出现过的 bug：以前 world/工具层/图三家各自数步，对账时才需要按步去重，
  结果出现过步号回退。
- **协议（interfaces/）里几乎全是 `...` 占位的抽象方法。** 具体实现只有
  `build.py` 认识；这一层的意义是让 Harness 换模拟器、换 LLM 供应商时一行
  不用改。
- **图结构本身承载设计规则，而不是靠代码里的调用顺序。** `retrieve_memory`/
  `remember`/`summarize` 拆成独立的图节点，是因为"每一步先查记忆再决策"
  "只有推进世界那一步才写记忆""一局只在结束时蒸馏一次经验"这三条规则
  现在从图的边上就能看出来，不用读代码才知道。
  推论是反过来也成立：**不花钱、不改世界、不写记忆的纯计算不该占一格**——
  构造 `EpisodeOutcome` 因此留在 `run()` 里，给它一个方框会稀释"读图 = 看这一局
  做了哪些真事"这个读法。
- **同一份信息只在一个地方算。** `EpisodeOutcome` 和 `EPISODE_END` 的 payload
  逐字段对应，所以它们写在相邻两行、从同一个 `obs` 派生。算在两个地方的话，
  漂移时**没有任何东西会报错**——返回值说成功、事件流说失败，要等到对账才发现。
- **跨层类型 vs 模块内部类型的界限很刻意。** `ObjectFact` 定义在
  `schemas/object_fact.py` 而不是 `memory/` 包内部，因为它要出现在
  `MemoryToolPort` 的签名里（跨层）；`ScreenState`/`TerrainMap` 虽然也在
  `schemas/observation.py`，但明确标注"不跨层"——只在 `PyBoyWorld` 内部
  产出、就地转换成 `Observation.facts` 里的字符串。

## 已知的过渡态

写这份规格时项目正处于几处过渡：

- `pokemon_agent/schemas/core.py`（旧的单文件契约）、
  `pokemon_agent/memory/object_memory.py`（旧的语义记忆实现）、
  `pokemon_agent/mocks/mock_trace.py`（`LocalTrace` 的旧位置，已搬到
  `pokemon_agent/trace/store.py`）、`probe/echo_trace.py`（`EchoTrace` 装饰器，
  打印逻辑已并入 `LocalTrace.sse()`）——这四个曾经的"应删除但尚未删除"文件
  **现已全部删除**，本节这条不变量记录到此为止；`trace/` 包的当前形态见
  `interfaces/SPEC.md` 第 4 节、`build/SPEC.md` 第 4、6 节。
- **拆子目标的机制不在了。** `Intent`/`push_goal`/多层并发判定（`_judge_all`）
  这一整套删掉了，目标栈的形状留着但恒为一层，当前目标恒为栈顶。
  重写它时要捡回来的那几条论证记在 `harness/SPEC.md` 第 5 节和
  `brain/SPEC.md` 3.4 的引用块里——**不留在代码里占位**，占位的抽象会把下一版
  往旧形状上带。
- **`inspect` 整条链路已经删除。** `WorldPort.inspect()` / `PyBoyWorld.inspect()` /
  `trace_utils.inspect()` / `facts["inspected"]` / `prompts/inspect_focus.md` /
  `JUDGE_BLIND` 里的那一项全部删掉——它长期**没有任何调用方**（brain 和 harness 里
  一处都没有，trace 里也从没出现过 INSPECT 事件），却带着一份 prompt、一个 4 条上限的
  缓存、一条 facts 键和一条黑名单条目在维护。
  **`EventType.INSPECT` 枚举成员保留**：旧的 trace 文件里有这类事件，删掉成员
  replay 会在校验那一步炸。观测台的 inspect 分支同理保留。两处都标了"没有生产者了"。
  它留下的那条经验记在 `prompts/SPEC.md` 4.2 和 5.2：细看和 `observe()` 的区别不在
  "再看一次"，而在**问的是不同的问题**——`observe()` 按帧缓存，同一帧再问一遍
  返回的字节完全一样。
- **`tests/` 整个目录在 `.gitignore` 里**（`git ls-files tests/` 是 0）。
  CLAUDE.md 第十节要求必须存在的那两个测试，对任何 clone 这个仓库的人都不存在。
- `LocalTrace` 是 `TracePort` 唯一的实现，但它**已经不只是内存实现了**：事件逐条
  追加落 JSONL（`trace_data/<run_id>/episodes/*.jsonl`），并通过 `browser.py` 的
  SSE 推给浏览器观测台。终端只打印账单、错误、目标出栈、episode 起止这几类；
  观测、记忆、推理、动作这七类由 `store.BROWSER_ONLY` 挡在终端之外，只在观测台看
  ——它们一条就是十几行，混进终端会把前一类冲掉。
  **按失败类型聚合统计**仍然没做（`build/SPEC.md` 里有完整说明）。
- **`tests/` 现在有四个文件**（`test_run_experiment.py` 真实环境端到端、
  `test_prompts.py` prompt 漂移、`test_trace.py` trace payload，以及几个 0 字节的
  占位文件）。但整个目录仍在 `.gitignore` 里，见上一条。
