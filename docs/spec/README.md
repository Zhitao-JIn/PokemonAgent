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
├── mocks/         TracePort 的内存实现
├── experiment/    实验 manifest（尚未接入主流程）
└── build.py       唯一的装配点（全项目唯一出现 `new` 具体实现的地方）

probe/             命令行脚本（跑真实 episode、调试工具）
```

各模块的详细规格：

- [`schemas/SPEC.md`](schemas/SPEC.md) —— 六个契约文件（task/observation/action/
  memory_episodic/memory_semantic/trace）的完整类型定义
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
- [`build/SPEC.md`](build/SPEC.md) —— 装配、异常类型、`MockTrace`、命令行入口

## 分层关系（谁认识谁）

```
probe/run_episode.py
        │  只 import build.py + errors + mocks/echo_trace
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
      GameTools    MemoryTool     Brain      MockTrace(+EchoTrace装饰)
      (tools/)      (tools/)    (brain/)      (mocks/)
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
   `TerrainMap` → 组装成 `Observation`。`Harness` 再调
   `MemoryToolPort.known_here()` 把语义记忆拼进 `facts["known_objects"]`。
2. **retrieve_memory**：`Harness` 调 `MemoryToolPort.query_episodic()` →
   `MemoryTool._overlap()` 按字符重叠打分，取回 `list[MemoryEntry]`
   （`schemas/memory_episodic.py`）。
3. **think**：`Harness` 把 `goals`/`obs`/`space`/`memories` 交给
   `BrainPort.choose()` → `Brain` 用 `prompts/decide_action.md` 组装 prompt →
   调 `LLMProvider.complete()` → 解析成一个合法的 `Action`
   （`schemas/action.py`），失败则重试并把 `retry_note.md` 塞进下一次 prompt。
4. **press / push_goal / inspect**：三选一，只有 `press` 真正调
   `GameToolPort.execute()` 推进世界。
5. **remember**（只在 press 之后）：`Harness` 调 `BrainPort.reflect()` 把
   前后两份 `Observation` 整理成一条 `MemoryEntry`，写回
   `MemoryToolPort.write_episodic()`；再调 `MemoryToolPort.note_step()`
   把这一步的语义记忆（门/招牌/人给出的信息）落进 `memory/` 包。
6. 每一步产生的所有模型调用记录（`calls`，见下一节）和状态转移，最终都由
   `Harness` 一个人翻译成 `TracePort.append()` 事件——这是全项目唯一写
   trace 的地方。

## 贯穿全项目的几条不变量

这些是分散在各模块规格里、但只有放在一起看才成立的规则：

- **只有 Harness 写 trace。** 大脑、工具、世界都只把"发生了什么"
  （`ModelCall`、`Observation`、`ToolResult`）当返回值交出来，翻译成事件是
  Harness 一个人的工作。这条规则最近的体现：模型调用记账从
  `drain_calls()` + 内部缓冲区（生产者/消费者通过可变状态搭桥）改成了
  `calls` 直接跟着 `PerceptionResult`/`ToolResult` 返回值走——
  `reset`/`perceive`/`inspect`/`execute` 四个方法各自把这次调用产生的账单
  原样交出来，Harness 在 `_begin`/`_press`/`_inspect`/`_observe` 里当场记账，
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
  `remember` 拆成独立的图节点（而不是 `think`/`press` 内部的几行代码），
  是因为"每一步先查记忆再决策""只有推进世界那一步才写记忆"这两条规则
  现在从图的边上就能看出来，不用读代码才知道。
- **跨层类型 vs 模块内部类型的界限很刻意。** `ObjectFact` 定义在
  `schemas/memory_semantic.py` 而不是 `memory/` 包内部，因为它要出现在
  `MemoryToolPort` 的签名里（跨层）；`ScreenState`/`TerrainMap` 虽然也在
  `schemas/observation.py`，但明确标注"不跨层"——只在 `PyBoyWorld` 内部
  产出、就地转换成 `Observation.facts` 里的字符串。

## 已知的过渡态

写这份规格时项目正处于几处过渡：

- `pokemon_agent/schemas/core.py`（旧的单文件契约，已被拆分成六个文件取代）
  和 `pokemon_agent/memory/object_memory.py`（旧的语义记忆实现，已被
  `memory/semantic/object_store.py` + `tools/memory_tool.py` 取代）
  这两个文件应当删除但尚未删除——项目里已经没有任何代码 import 它们。
- `experiment/manifest.py` 定义了实验配置骨架，但尚未接入
  `probe/run_episode.py` 这个主入口。
- `MockTrace` 是 `TracePort` 唯一的实现——落盘、SSE 推流、按失败类型聚合统计
  都还没做（`build/SPEC.md` 里有完整说明）。
