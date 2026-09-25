# schemas —— 模块规格

> 最后更新：2026-09-24 ｜ 活文档：跟随代码更新，与代码冲突时以代码为准

## 一、职责与边界

`pokemon_agent/schemas/` 是**本项目自己的跨层契约层**：装的全是 Pydantic 数据模型——模块间的信封、模块对外的接口模型，以及"只在 tool 层与各自组装方之间流动"的跨层数据形状。

- **不做根出口**：`schemas/__init__.py` **不 re-export 任何名字**，只留 docstring。出口做在每个产出模块一级——消费方写 `from pokemon_agent.schemas.harness import X` 或 `from pokemon_agent.schemas.memory import X`，**不深到 `communication/` / `datastore/` 子目录**。这样 import 行本身就说明"这个文件跟哪几个协作者的契约打交道"，也避免同一名字有两条 import 路径。
- **只留真正的信封**：`schemas/` 下现存**只有 `harness/` 与 `memory/` 两个子包**。`frontend/`（0914 控制台改造整个删除）、`providers/`（0913 深夜十一随代码层 `pokemon_agent/providers/` 一起解散）都不在了；`brain` / `world` / `trace` 也没有自己的 `schemas/` 子包——它们的数据形状物理上归回产出它们的模块自己（`brain/interface/domain/`、`world/interface/domain/`、`trace/datastore/`）。
- **不给 tool 门面单开子包**：harness 经门面调模块的架构不变，信封仍在 `harness/communication/` 下按"往哪个门面"分。
- **`schemas/harness/domain/` 不许 import `pokemon_agent.trace`**——守的是**分层方向**（契约层不反向依赖实现包）。⚠ **不是"防环"**：trace 出边为零，这里 import 它也不会成环（0916 实测四种加载顺序全不炸）；0913 脱钩**之前**才是真环（那时 `trace.store` 反向 import 本包）。可执行核对：`scripts/check_trace_self_contained.py` 的 C 项。

## 二、目录结构

```
schemas/
├── __init__.py                       不是出口，不 re-export 任何名字
├── harness/
│   ├── __init__.py                   出口：信封名 + domain 各件 + AuditVerdict / ModelCall / ModelCallLog / RunResp
│   ├── communication/                信封模块（一文件一信封；`FromHarnessToReviewerAuditReq.py` 一文件两信封 + AuditVerdict）
│   └── domain/
│       ├── __init__.py               出口：EpisodeInput / EpisodeOutput / TaskInput / TaskOutput / Termination /
│       │                             Settled / EntryStatus / GoalEntry / TaskEntry / TraceEvent / TraceKind
│       ├── episode_io.py             EpisodeInput / EpisodeOutput（run ↔ episode）
│       ├── task_io.py                TaskInput / TaskOutput（episode ↔ task）
│       ├── termination.py            Termination（五类）+ Settled（done / success 两个派生属性的混入类）
│       ├── entry_status.py           EntryStatus（目标表与任务表共用的五个状态）
│       ├── goal_entry.py             GoalEntry（run 目标表的一行）
│       ├── task_entry.py             TaskEntry（episode 任务表的一行）
│       ├── trace_event.py            TraceEvent
│       └── trace_kind.py             TraceKind
└── memory/
    ├── __init__.py                   出口：SNAPSHOT_BLIND / ActMemory / TaskMemory / EpisodeMemory / KnowledgeRecord /
    │                                 ObjectDialogEvent / ObjectFactEvent / ObjectStillEvent / ObjectWarpEvent / render_sequence
    └── datastore/
        ├── act_memory.py             ActMemory / SNAPSHOT_BLIND / render_sequence
        ├── task_memory.py            TaskMemory
        ├── episode_memory.py         EpisodeMemory
        ├── object_memory.py          ObjectFactEventBase / 三个子类 / ObjectFactEvent
        └── knowledge.py              KnowledgeRecord
```

两个出口文件都**只做 re-export、不定义实体**。`communication/` 与 `datastore/` 子目录不对外。
计数以 `ls` 与 `__all__` 为准，本文不抄数字。

## 三、信封清单

按"往哪个门面"分组（文件名即信封名）：

- **往 `brain_tool`**：`ChooseOnce`、`PlanOnce`、`Decompose`、`Judge`、`Reflect`、`Verify`、`Summarize`、
  `SummarizeTask`，各一对 `Req` / `Resp`（前缀 `FromHarnessToBrainTool`）。
  - `JudgeReq` 带 `task_memories` / `task_table` / `episode_memories`（episode / run 层判定的素材）。
  - `DecomposeReq` 带 `task_table`（本局任务表，成败以表为准）。
  - `SummarizeReq` / `SummarizeTaskReq` 带 `verdicts`（正负标注）、`termination`、`acts_used`；`success` 是推出的属性。
  - `PlanOnceReq` 带 `human_note`。
- **往 `game_tool`**：`Reset`、`Execute`、`Evolve`、`GetActionSpace`、`PerceiveOnce`。
- **往 `memory_tool`**：ActMemory（`StoreActMemory` / `QueryActMemories` / `QueryRecentActMemories`）、
  TaskMemory（`StoreTaskMemory` / `QueryTaskMemories`）、EpisodeMemory（`StoreEpisodeSummary` / `QueryEpisodeSummaries`）、
  物件（`AppendObjectEvents` / `QueryObjectEvents` / `QueryObjectEventsAt`）、知识（`StoreKnowledge` / `QueryKnowledge`）、
  快照（`SnapshotMemory` / `RestoreMemory`）。
- **往 `reviewer`**：`InjectReq`、`AuditReq` / `AuditResp`（`AuditReq.outcome` 是 `EpisodeOutput` 或 `TaskOutput`，
  审 task 时 `task_id` 非空，`events` 是被审对象自己的 trace）。
- **往 `trace_tool`**：`FromHarnessToTraceToolAppendReq`——`kind` + `meta`（调用方交四件：`source`/`episode_id`/`task_id`/`step`；`run_id`/`branch` 由落盘层盖）+ 各 kind 取用的可选字段
  （`calls` / `obs` / `entry` / `verdicts` / `outcome_task` / `goal` / `task_entry` / `abandoned` / `audit` / `tasks` /
  `termination` / `fail_streak` / `updates` …）。
- **非门面**：`ModelCall.py`（`ModelCall` / `ModelCallLog`）、`RunResp.py`（`RunResp`：outcomes / total / succeeded / success_rate / termination；混入 `Settled`）。

**层间交接不走信封**：run → episode → task 的交接是 `domain/` 的 `EpisodeInput/Output`、`TaskInput/Output`
（裸名；旧的 `FromRunHarnessToEpisodeHarnessRun{Req,Resp}` 已删）。

## 四、命名规则

**规则一（信封）**：`From[模块A]To[模块B][函数名][Req/Resp]`，**两半都放 A 处（发起方）**。强制适用范围是 **Harness ↔ 各门面**这一跳（brain_tool / game_tool / memory_tool / reviewer / trace_tool），层间交接用 domain 的 IO 模型，不造信封。第一跳（调用方 → 模块门面）永远是信封，**门面上的每个方法都算**。

- **外壳（experiment）→ Harness 这条边不包装**：外壳不是我们的模块，入参与返回值都走裸字段——`run(run_id, goals, run_goal=None)` 返回 `(outcomes, total, succeeded, success_rate)`。
- 有入参就有 Req；返回结构化载荷就有 Resp；**返回 `None` 的没有 Resp**。现有先例：`FromHarnessToGameToolResetReq`、`FromHarnessToReviewerInjectReq`、`FromHarnessToMemoryToolAppendObjectEventsReq`、`FromHarnessToMemoryToolStoreActMemoryReq`。
- 别把这条推到记账层：**信封该内嵌模型就内嵌模型**——`run_end` 里的 `RunResp` 由 `harness/run/run_entry.py::close()` 内部组装，跟 `run()` 返回什么无关。

**规则二（裸名）**：模块对外的接口模型用裸名、不带 From/To——因为发起方可能换人（今天 harness，明天第三方），From/To 前缀是赌一个注定被换掉的名字。**适用范围到此为止**：

- 在 `schemas/` 里落地的裸名只有 `RunResp` 与 `ModelCall`（加上 `domain/` 的实体 `TraceKind` / `TraceEvent` / `GoalEntry` / `GoalStatus`，以及 `ModelCall.py` 里的 `ModelCallLog` 别名、只服务审的 `AuditVerdict`）。
- 其余裸名住在各自模块内，**不在 `schemas/`**：brain 的 `LlmCompleteReq` 在 `pokemon_agent/brain/schemas/completion.py`，world 的 `Perceived` 在 `pokemon_agent/world/interface/domain/perceived.py`。
- **第二跳（门面 → 具体模块）走裸参数、返回模块自己的类型**，不造信封也不新建模型。

## 五、domain 实体与归属

**按产出方归属**：谁声明这个形状，它就住谁的包；跨包引用只允许向下。

| 实体 | 家 | 声明 / 产出方 | 谁引用它 |
|---|---|---|---|
| `TraceKind` / `TraceEvent` | `harness/domain/` | harness（各格声明"我记哪笔账"） | `FromHarnessToTraceToolAppendReq`、`…AuditReq` |
| `EntryStatus` | `harness/domain/entry_status.py` | 两张表共用的状态 | `GoalEntry`、`TaskEntry` |
| `GoalEntry` | `harness/domain/goal_entry.py` | run 级目标表的一行（`task`/`status`/`attempts`/`last_episode_id`/`note`/`overturned`） | `…PlanOnceReq`、`RunState.goals` |
| `TaskEntry` | `harness/domain/task_entry.py` | episode 任务表的一行（`task`/`status`/`note`/`overturned`/`round`） | `EpisodeRunState.tasks`、`…DecomposeReq`、`…JudgeReq` |
| `EpisodeInput` / `EpisodeOutput` | `harness/domain/episode_io.py` | run.act / episode 入口 | `RunState`、`RunResp.outcomes`、`RunState.episode_outputs` |
| `TaskInput` / `TaskOutput` | `harness/domain/task_io.py` | episode.act / task 入口 | `EpisodeRunState` |
| `Termination` / `Settled` | `harness/domain/termination.py` | 三层 `review_and_judge` | 三层 state、两个 `*Output`、`RunResp`、两封 Summarize 请求；`TaskMemory` / `EpisodeMemory` 的章（字符串） |
| `ActMemory` / `TaskMemory` / `EpisodeMemory` | `memory/datastore/` | 本项目（tool 层组装） | brain_tool / memory_tool 信封 |
| `ObjectFactEvent` 族 / `KnowledgeRecord` | `memory/datastore/` | 同上 | 物件 / 知识信封 |

`schemas/memory/**` 零外部 import（`ActMemory.Observation` 等快照类是刻意的内部声明）；
`harness/communication/*` 向下引用 `pokemon_agent.brain.interface`（`Action` / `Goal` / `Task` / `RunPlan` /
`Decomposition` / `EpisodeSummary` / `VerifyVerdict`）与 `pokemon_agent.world`（`ActionSpace` / `Observation` / `PlaceInWorld`）。

## 六、记忆一族的形状（记忆阶梯）

| 记录 | 一条 = 什么 | 坐标 / 身份 | 谁写 |
|---|---|---|---|
| `ActMemory` | **一键**——源记录 | `(episode_id, task_id, step)` | task.perceive `store_step_episode_memory` |
| `TaskMemory` | **一个 task**——对本 task ActMemory 的蒸馏 | `task_id` | task_done `summarize_task` |
| `EpisodeMemory` | **一局**——对本局 TaskMemory 的蒸馏 | `episode_id`；每局恰好一条 | episode_done `summarize_episode`（异常局由 run 补空章） |
| `ObjectFactEvent` | 一格的一次交互 | `Place.key` = `"{map_id}:{x}:{y}"` | task.perceive `store_object_semantic_memory` |
| `KnowledgeRecord` | 不挂坐标的世界知识 | `topic` | 人管理（自动抽取已删） |

- **`ActMemory`**：`before` / `after`（内部快照类）、`rationale`、`action`（一个键）、签名 `run_id` / `episode_id` /
  `task_id` / `step`、截图 `before_frame` / `after_frame`。`render(reason=False)` 给判定器用——**判定器读不到决策者的理由**。
- **`TaskMemory`**：章（`task_id` / `goal` / `termination`（`success` 是由它推出的属性） / `steps_used` / `start_step`）+ LLM 正文
  （`summary` / `reason` / `reusable_patterns` / `critical_decisions` / `failure_points` / `quality_*` / `tags` / `markdown`）+ 首末帧。
- **`EpisodeMemory`**：章（`episode_id` / `run_id` / `goal` / `termination`（`success` 由它推出） / `steps`=task 数 / `acts_used`）+ 同形正文 + `reason`。
- **派生关系**：上一级是下一级的派生视图（可重建、可丢弃）；**成败只认章不认正文**。verify 给每条下级记忆标正 / 负，
  summarize 两组都读——负样本也是参考。
- **`ObjectFactEvent` 族**：写时定型（`dialog` / `warp` / `still`，判别键 `outcome`），事件流是唯一真源。

## 七、已知缺口

- **有 Req 无 Resp 的信封**是约定（返回 `None` 就没有 Resp），不是遗漏。
- **`FromHarnessToReviewerAuditResp` 与 `AuditVerdict` 同住 `…AuditReq.py`**：文件名比内容窄。
- **`schemas/harness/__init__.py` 的 `__all__` 手工维护**：加一封信要同时改 import 与 `__all__`。
- **磁盘上 ActMemory 的集合名仍叫 `step_memory`**（`tools/memory_tool.py`），类名已是 `ActMemory`。
