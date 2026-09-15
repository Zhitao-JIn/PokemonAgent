# schemas —— 模块规格

> 最后更新：2026-09-15 ｜ 活文档：跟随代码更新，与代码冲突时以代码为准

## 一、职责与边界

`pokemon_agent/schemas/` 是**本项目自己的跨层契约层**：装的全是 Pydantic 数据模型——模块间的信封、模块对外的接口模型，以及"只在 tool 层与各自组装方之间流动"的跨层数据形状。

- **不做根出口**：`schemas/__init__.py` **不 re-export 任何名字**，只留 docstring。出口做在每个产出模块一级——消费方写 `from pokemon_agent.schemas.harness import X` 或 `from pokemon_agent.schemas.memory import X`，**不深到 `communication/` / `datastore/` 子目录**。这样 import 行本身就说明"这个文件跟哪几个协作者的契约打交道"，也避免同一名字有两条 import 路径。
- **只留真正的信封**：`schemas/` 下现存**只有 `harness/` 与 `memory/` 两个子包**。`frontend/`（0914 控制台改造整个删除）、`providers/`（0913 深夜十一随代码层 `pokemon_agent/providers/` 一起解散）都不在了；`brain` / `world` / `trace` 也没有自己的 `schemas/` 子包——它们的数据形状物理上归回产出它们的模块自己（`brain/interface/domain/`、`world/interface/domain/`、`trace/datastore/`）。
- **不给 tool 门面单开子包**：harness 经门面调模块的架构不变，信封仍在 `harness/communication/` 下按"往哪个门面"分。
- **`schemas/harness/domain/` 不许 import `pokemon_agent.trace`**——一 import 就成环（`schemas.harness` → `trace` → `trace.store` → `schemas.harness.domain` 半加载 → `ImportError`）。可执行核对：`scripts/check_trace_self_contained.py` 的 C 项。

## 二、目录结构

```
schemas/
├── __init__.py                       不是出口，不 re-export 任何名字
├── harness/
│   ├── __init__.py                   出口：44 个信封 + domain 四件 + AuditVerdict / ModelCall / ModelCallLog / RunResp
│   ├── communication/                46 个模块 + __init__.py（44 个信封 + ModelCall / RunResp）
│   └── domain/
│       ├── __init__.py               出口：GoalEntry / GoalStatus / TraceEvent / TraceKind
│       ├── goal_entry.py             GoalEntry / GoalStatus
│       ├── trace_event.py            TraceEvent
│       └── trace_kind.py             TraceKind
└── memory/
    ├── __init__.py                   出口：SNAPSHOT_BLIND / EpisodeMemory / KnowledgeRecord /
    │                                 ObjectDialogEvent / ObjectFactEvent / ObjectStillEvent /
    │                                 ObjectWarpEvent / StepMemory / dedup_snapshots / render_sequence
    └── datastore/
        ├── __init__.py               出口：上列 10 个 + ObjectFactEventBase
        ├── step_memory.py            StepMemory / SNAPSHOT_BLIND / render_sequence / dedup_snapshots
        ├── episode_memory.py         EpisodeMemory
        ├── object_memory.py          ObjectFactEventBase / ObjectDialogEvent / ObjectWarpEvent /
        │                             ObjectStillEvent / ObjectFactEvent
        └── knowledge.py              KnowledgeRecord
```

两个出口文件都**只做 re-export、不定义实体**。`communication/` 与 `datastore/` 子目录不对外。

**这里只有这两个子包。** `schemas/trace/`、`schemas/world/`、`schemas/memory/communication/` 曾各剩一个空骨架（数据已按"归产出它的模块自己"归回，目录没清），2026-09-15 一并移进 `_to_delete/0915-empty-schemas-skeleton/`；`brain/`、`providers/`、`frontend/` 三个子包更早就整个没了（`schemas/__init__.py` 顶部有逐条去向）。

## 三、信封清单

`harness/communication/` 下 **46 个模块**（另有 `__init__.py`，目录共 47 个 `.py`）：**44 个信封**（各门面第一跳 + run → episode 内部边）+ 2 个接口模型 / 账模块。按"往哪个门面"分组：

### 往 `brain_tool`（14）

| 模块 | 干什么 |
|---|---|
| `FromHarnessToBrainToolChooseOnceReq` / `…Resp` | 决策：要一次动作选择 / 返回选出的动作 |
| `FromHarnessToBrainToolExtractReq` / `…Resp` | 世界知识抽取 / 返回抽出的知识记录 |
| `FromHarnessToBrainToolJudgeReq` / `…Resp` | 判定（这一局成没成） |
| `FromHarnessToBrainToolPlanOnceReq` / `…Resp` | run 级规划 |
| `FromHarnessToBrainToolReflectReq` / `…Resp` | 反思：把一步固化成 `StepMemory` |
| `FromHarnessToBrainToolSummarizeReq` / `…Resp` | 蒸馏：把一局可信 step 记忆压成跨局摘要 |
| `FromHarnessToBrainToolVerifyReq` / `…Resp` | 校验：逐步判定 |

（7 对 = 14 个模块。）

### 往 `game_tool`（6）

| 模块 | 干什么 |
|---|---|
| `FromHarnessToGameToolExecuteReq` | 动作执行请求（无 Resp） |
| `FromHarnessToGameToolResetReq` | 开局重置请求（`reset()` 返回 `None`，无 Resp 的先例） |
| `FromHarnessToGameToolEvolveReq` | 空转推进请求（无 Resp） |
| `FromHarnessToGameToolGetActionSpaceReq` / `…Resp` | 取这一步允许的动作名 |
| `FromHarnessToGameToolPerceiveOnceResp` | 单次感知响应（**没有 Req 文件**：感知由本层发起、`ram_only` 走裸参） |

### 往 `memory_tool`（18）

| 模块 | 干什么 |
|---|---|
| `FromHarnessToMemoryToolStoreEpisodeStepReq` | 写入一条单步记忆（无 Resp） |
| `FromHarnessToMemoryToolStoreEpisodeSummaryReq` / `…Resp` | 写入一局跨局摘要 |
| `FromHarnessToMemoryToolStoreKnowledgeReq` / `…Resp` | 写入一条世界知识 |
| `FromHarnessToMemoryToolAppendObjectEventsReq` | 追加一批交互事件（无 Resp） |
| `FromHarnessToMemoryToolQueryRecentStepsReq` / `…Resp` | 检索近期单步记忆 |
| `FromHarnessToMemoryToolQueryEpisodeStepsReq` / `…Resp` | 检索整局单步记忆 |
| `FromHarnessToMemoryToolQueryEpisodeSummariesReq` / `…Resp` | 读跨局摘要 |
| `FromHarnessToMemoryToolQueryKnowledgeReq` / `…Resp` | 知识检索 |
| `FromHarnessToMemoryToolQueryObjectEventsReq` / `…Resp` | 整图交互事件检索 |
| `FromHarnessToMemoryToolQueryObjectEventsAtReq` / `…Resp` | 指定格子的交互事件检索 |

### 往 `reviewer`（2 个模块 / 3 个类）

| 模块 | 干什么 |
|---|---|
| `FromHarnessToReviewerInjectReq` | **插话**请求：人收一句自然语言（`inject()` 返回字符串之外无结构化载荷，无 Resp） |
| `FromHarnessToReviewerAuditReq` | **审**：文件里定义三个类——`AuditVerdict`（`accept` / `overturn`）、`FromHarnessToReviewerAuditReq`（一局的机械结算 + 完整 trace）、`FromHarnessToReviewerAuditResp`（人的表态）。**Resp 与 Req 同文件，没有独立的 `…AuditResp.py`** |

### 往 `trace_tool`（2）

| 模块 | 干什么 |
|---|---|
| `FromHarnessToTraceToolAppendReq` | 单笔记账请求：`kind`（`TraceKind`）+ `meta`（签名信息）+ 各 kind 取用的可选领域字段（`calls` / `obs` / `entry` / `verdicts`…） |
| `FromHarnessToTraceToolAppendModelCallsReq` | 批量记账请求：一笔模型交互的全部尝试；同文件定义 `ModelCallLog` |

### run → episode 内部边（2）

| 模块 | 干什么 |
|---|---|
| `FromRunHarnessToEpisodeHarnessRunReq` | 一局的派发请求 |
| `FromRunHarnessToEpisodeHarnessRunResp` | 一局的结算（`RunResp.outcomes` 的元素类型） |

### 非门面：接口模型 / 账（2）

| 模块 | 干什么 |
|---|---|
| `ModelCall.py` | `ModelCall`：一次模型调用留下的账（`payload` / `error_kind` / `error`），由 `FromHarnessToTraceToolAppendReq.calls` 内嵌 |
| `RunResp.py` | `RunResp`：RunHarness 对外的 run 结算（裸名），由 `harness/run/run_entry.py::close()` 内部组装、供 `run_end` 事件内嵌 |

## 四、命名规则

**规则一（信封）**：`From[模块A]To[模块B][函数名][Req/Resp]`，**两半都放 A 处（发起方）**。强制适用范围是 **Harness ↔ 各门面**这一跳（brain_tool / game_tool / memory_tool / reviewer / trace_tool），外加 run → episode 这条内部边。第一跳（调用方 → 模块门面）永远是信封，**门面上的每个方法都算**。

- **外壳（experiment）→ Harness 这条边不包装**：外壳不是我们的模块，入参与返回值都走裸字段——`run(run_id, goals)` 返回 `(outcomes, total, succeeded, success_rate)`。
- 有入参就有 Req；返回结构化载荷就有 Resp；**返回 `None` 的没有 Resp**。现有先例：`FromHarnessToGameToolResetReq`、`FromHarnessToReviewerInjectReq`、`FromHarnessToMemoryToolAppendObjectEventsReq`、`FromHarnessToMemoryToolStoreEpisodeStepReq`。
- 别把这条推到记账层：**信封该内嵌模型就内嵌模型**——`run_end` 里的 `RunResp` 由 `harness/run/run_entry.py::close()` 内部组装，跟 `run()` 返回什么无关。

**规则二（裸名）**：模块对外的接口模型用裸名、不带 From/To——因为发起方可能换人（今天 harness，明天第三方），From/To 前缀是赌一个注定被换掉的名字。**适用范围到此为止**：

- 在 `schemas/` 里落地的裸名只有 `RunResp` 与 `ModelCall`（加上 `domain/` 的实体 `TraceKind` / `TraceEvent` / `GoalEntry` / `GoalStatus`，以及只服务一个信封的 `ModelCallLog`、只服务审的 `AuditVerdict`）。
- 其余裸名住在各自模块内，**不在 `schemas/`**：brain 的 `LlmCompleteReq` 在 `pokemon_agent/brain/schemas/completion.py`，world 的 `Perceived` 在 `pokemon_agent/world/interface/domain/perceived.py`。
- **第二跳（门面 → 具体模块）走裸参数、返回模块自己的类型**，不造信封也不新建模型。

## 五、domain 实体与归属

**按产出方归属**：谁声明这个形状、谁消费它，它就住谁的包。**跨包引用只允许向下**（聚合方 → 被聚合方），代码里实际成立的引用如下：

| 实体 | 家 | 声明 / 产出方 | 谁引用它 |
|---|---|---|---|
| `TraceKind` | `harness/domain/trace_kind.py` | harness（各节点声明"我记哪笔账"） | `FromHarnessToTraceToolAppendReq`、`…AppendModelCallsReq`；消费方是 `TraceTool` 渲染层 |
| `TraceEvent` | `harness/domain/trace_event.py` | 项目侧对 trace 事件的形状声明 | `FromHarnessToReviewerAuditReq.episode_trace` |
| `GoalEntry` / `GoalStatus` | `harness/domain/goal_entry.py` | harness（run 级目标表的一行） | `FromHarnessToBrainToolPlanOnceReq` |
| `StepMemory` | `memory/datastore/step_memory.py` | 本项目（tool 层与组装方认识它的字段） | `FromHarnessToBrainTool*` 6 个信封、`FromHarnessToMemoryTool*` 3 个信封 |
| `EpisodeMemory` | `memory/datastore/episode_memory.py` | 同上 | `…PlanOnceReq`、`…SummarizeResp`、`…StoreEpisodeSummaryReq/Resp`、`…QueryEpisodeSummariesResp` |
| `ObjectFactEvent` 族 | `memory/datastore/object_memory.py` | 同上 | `…PlanOnceReq`、`…AppendObjectEventsReq`、`…QueryObjectEventsResp`、`…QueryObjectEventsAtResp` |
| `KnowledgeRecord` | `memory/datastore/knowledge.py` | 同上 | `…ExtractResp`、`…StoreKnowledgeReq/Resp` |

**跨包引用登记（schemas 内实际存在的出边）**：

| 引用方 | 被引用 | 说明 |
|---|---|---|
| `harness/domain/goal_entry.py` | `pokemon_agent.brain`（`Task`） | `GoalEntry.task` 是 brain 的领域模型，一字不改 |
| `harness/communication/*`（多封信） | `pokemon_agent.brain.interface`（`Action` / `ActionSegment` / `Goal` / `RunPlan` / `EpisodeSummary` / `StepVerifyVerdict` / `Task`） | 跨层信封内嵌 brain 的数据形状 |
| `harness/communication/*` | `pokemon_agent.world`（`ActionSpace` / `Observation` / `PlaceInWorld`） | 同上，world 的形状 |
| `harness/communication/*` | `pokemon_agent.schemas.memory` | 同包内向下（harness → memory） |
| `harness/communication/*` | `pokemon_agent.schemas.harness.domain` | 同包内 |
| `schemas/memory/**` | 零外部 import | 那几个"形状像但类不同"的内部快照类（`StepMemory.Observation` 及其 `Facts` / `Landmark`、`StepMemory.Place`、`ObjectFactEventBase.Place`）是**刻意的内部声明**，不 import `pokemon_agent.world` |

**`trace` 是最底层共用层**：任何包都可引用它，它自己零跨包引用。schemas 侧对它**零 import**——`TraceEvent` 是结构化副本（字段结构对得上、不共享类型）。

## 六、记忆一族的形状

四条记录按**检索单元**命名，各有各的坐标轴：

| 记录 | 一条 = 什么 | 坐标 / 身份 |
|---|---|---|
| `StepMemory` | **一步**——源记录 | `(episode_id, step)`；一步一条，唯一且语义稳定 |
| `EpisodeMemory` | **一整局**——派生物 | `episode_id`；每局恰好一条（**硬约束**） |
| `ObjectFactEvent` | **一格的一次交互** | `ObjectFactEventBase.Place.key` = `"{map_id}:{x}:{y}"`，跨 episode 稳定 |
| `KnowledgeRecord` | **一条不挂坐标的世界知识** | `topic`；`run_id` / `episode_id` 只是来源，不是身份 |

**`StepMemory`（源）**：字段分三段——观察前 / 后（`before` / `after`，各是内部类 `StepMemory.Observation`，唯二的快照副本）、`rationale`（`ActionSegment.rationale` 的论据）、`action`（**一个键**）；签名三元组 `step` / `episode_id` / `run_id`；截图 `before_frame` / `after_frame`（**base64 编码的 PNG 字符串**，可能是 `None`）。`render(reason=True)` 同时服务 prompt 与检索打分；`reason=False` 去掉「因为」那一行，判定器用这一版——**绝不能读到决策者的理由**。模块级常量 `SNAPSHOT_BLIND = frozenset({"known_objects", "knowledge"})`（不进记忆的字段，**排除表而不是白名单**）、`BLIND_NOTE`（没做过视觉感知时必须顶的那一行）。两个纯函数：`render_sequence()`（相邻两条首尾相接时只渲一次边界）、`dedup_snapshots()`（摊平成 `(before, after, …)` 去重，返回严格等长的 `(frames, snapshots)`）。

**派生关系**：`EpisodeMemory` 的**正文**（`summary` 起）由 LLM 从**本局通过校验的那些 `StepMemory`** 蒸馏而来（过滤点在 `harness/episode/close/verify_and_summarize.py`），所以它是 `StepMemory` 的**派生视图**——**可重建、可丢弃**，`rm memory/episode_memory/*.md` 只损失算力不损失事实。它的**来源章**（`episode_id` / `run_id` / `goal` / `success` / `steps`）与 step memory 无关，是 harness 从 run state 盖的。三条推论：可重建、可丢弃、**成败只认章不认正文**（`render()` 把章摆在第一行）。

**`ObjectFactEvent` 族**：**写时定型**，三个子类各占一种结局，公共字段在 `ObjectFactEventBase`（`episode_id` / `step` / `run_id` / `actor_place` / `place` / `object_kind` / `button`）。`ObjectDialogEvent`（`outcome="dialog"` + `text`）、`ObjectWarpEvent`（`outcome="warp"` + `map_id`）、`ObjectStillEvent`（`outcome="still"`）。`ObjectFactEvent` 是 `Annotated[三个子类, Field(discriminator="outcome")]` 的联合类型，消费方**按类型分发**，不允许按 payload 内容猜语义。判别键叫 `outcome`（不是 `type`）、类别叫 `object_kind`——因为封套的 `type` / `kind` 是 trace 保留字。事件流是**唯一真源**，落盘按局分文件（`ep-{id}.jsonl`），一旦落库不可变（修正靠新事件或恢复时截断）。

**`KnowledgeRecord`**：`topic` / `text` / `source` / `run_id` / `episode_id`。和 `ObjectFactEvent` 的分界是**坐标**（知识刻意不带坐标）；和 `EpisodeMemory` 的分界是**归属**（摘要属于那一局，知识属于世界）。落盘形态与手工先验**逐字一致**：metadata 放过滤字段、payload 空、正文是 `text`，所以读口 `query_knowledge` 不需要区分两种来源。`render()` 就是 `text` 本身——知识没有"成没成"可言，不需要来源章。

## 七、当前状态与已知缺口

- **信封覆盖完整但不对称**：有 6 个 Req 没有配对的 Resp——`FromHarnessToGameToolResetReq`、`FromHarnessToGameToolExecuteReq`、`FromHarnessToGameToolEvolveReq`、`FromHarnessToReviewerInjectReq`、`FromHarnessToMemoryToolAppendObjectEventsReq`、`FromHarnessToMemoryToolStoreEpisodeStepReq`；`FromHarnessToGameToolPerceiveOnceResp` 反过来没有配对 Req。都是调用方约定（返回 `None` 就没有 Resp；感知由本层发起），不是遗漏。
- **`FromHarnessToReviewerAuditResp` 没有独立文件**：它与自己的 Req、`AuditVerdict` 同住 `FromHarnessToReviewerAuditReq.py`，`harness/__init__.py` 从那一个文件一起 import 三个名字。文件名比它的内容窄。
- **`memory/__init__.py` 不导出 `ObjectFactEventBase`**，而 `datastore/__init__.py` 导出它——外部拿基类只能深到 `schemas.memory.datastore`。
- **`schemas/harness/__init__.py` 的 `__all__` 手工维护 53 个名字**：import 与 `__all__` 各写一遍、靠人对照，加一封信要同时改两处。

## 发现的不一致

（以下以代码为准。）

1. **`communication/` 的实际规模是 47 个 `.py`**（44 个信封 + `ModelCall.py` + `RunResp.py` + `__init__.py`），不是"48 个文件"——`ls -1` 的 48 行里含一个 `__pycache__` 目录项。
2. `AGENTS.md` 十二、第 4 条的**跨包引用登记已失效**两处：(a) 把 `frontend → harness/brain` 列为一条有效下向引用，但同节已声明 `schemas/frontend/` 于 0914 整个删除；(b) 列了 `memory → world`，而 `schemas/memory/**` 实际对 `pokemon_agent.world` **零 import**（那三份快照是刻意的内部副本）。
3. `AGENTS.md` 十二、第 2 条举例的裸名有两个在代码里**已不存在**：brain 的 `ChooseOnceReq`（现为 `pokemon_agent/brain/interface/domain/` 一族 + `pokemon_agent/brain/schemas/completion.py::LlmCompleteReq`；仓内只剩 `FromHarnessToBrainToolChooseOnceReq` 与 docstring 里对旧名的提及）、world 的 `PerceiveOnceResp`（现为 `pokemon_agent/world/interface/domain/perceived.py::Perceived`，该文件注明"不再嵌套一层 `PerceiveOnceResp`"）。
4. `AGENTS.md` 十二、第 5 条与 `RunResp` 的说明都写"五个字段是 `RunHarness.close()` 自己数出来的"——但 `RunHarness`（`pokemon_agent/harness/run/harness.py`）**没有 `close` 方法**（只有 `run` / `read_events` / `_compile`）；组装点是模块级函数 `pokemon_agent/harness/run/run_entry.py::close()`，它同时把 `meta.source` 记成 `"run_entry.close"`。
5. `AGENTS.md` 十二、第 1 条把 **`game_tool` 与 `memory_tool` 已于 0910 补齐**写成"此前只有 `query_knowledge` 一条"的历史对照——现网两家的模块计数是 game_tool 6、memory_tool 18，与本节表格一致，那句描述的旧状态早已不成立。
