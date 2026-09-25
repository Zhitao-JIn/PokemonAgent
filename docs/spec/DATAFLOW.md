# 数据流与落账（DATAFLOW）

> 2026-09-24（CHANGELOG 195–203）。图见 [`diagrams/`](diagrams/)，项目思想见 [`OVERVIEW.md`](OVERVIEW.md)。
> **以代码为准**：格集以 `harness/*/*_graph.py` 的 `add_node` 为真源，账名以
> `schemas/harness/domain/trace_kind.py` 为真源，正文字段以 `tools/trace/render.py` 为真源，
> 执行序以 `experiment/real_check/node_io.py` 的三张后继表为真源。

## 一、端到端

三张同构的 LangGraph 图，一层一个状态载体：

| 层 | 图 | 状态 | 一圈 = | `state.step` 数的是 |
|---|---|---|---|---|
| run | `run_graph` | `RunState` | 派一局 episode | 已派局数 |
| episode | `episode_graph` | `EpisodeRunState` | 派一个 task | 已派 task 数 |
| task | `task_graph` | `TaskState` | 按一次键 | 本 task 已按键数 |

每张图都是 `perceive → review_and_judge →(done? *_done : plan_*) → act → perceive`：

- **perceive**：吸收下层上一圈的结算 → **取帧**（episode 完整档、task RAM 档；run 不取）→
  **读直属下一级的记忆**与世界事实，装好本圈上下文（`plan_ctx` / `ep_ctx` / `task_ctx`）。
  本层其余各格只用这份上下文，不自己查库。
- **review_and_judge**：run / episode 先**定案上一条**（盖章 → 人审可推翻 → 记 `settle_goal` /
  `settle_task`），再判停：机械三类（世界终局 / 停滞 / 预算）→ 问 LLM judge。共用
  `harness/judging.py`。**唯一的停机点**，写 `termination`（`done` / `success` 由它推出）与
  `judge_reason`（判定依据：判定员的理由 / 机械判停类别），**不写** `reason`。
- **plan_\***：run 排目标表（Planner），episode 在没有 PENDING 时拆下一版任务（Decomposer，
  追加进任务表），task 选下一个键（Chooser，只执行首段 `times=1`）。
- **act**：run / episode 从表里派第一条 PENDING（标 RUNNING）、调下层入口
  （`episode_entry.run_episode` / `task_entry.run_task`），结算写进 `pending_*`；task 按键、`step+1`。
  **下层抛错由这一格接住**：记 `episode_error` / `task_error`，`AgentError` 兜成 `termination=error`
  的结算（这一 run / 这一局照常往下走），别的异常记完原样上抛。
- ***_done**：episode / task 的收尾链——verify（给下级记忆逐条标正 / 负）→ summarize（写本层
  记忆，`reason` 在这里由 LLM 写）→ close（写 `*_end`，交出 `*Output`）。没有下级记忆就跳过
  标与蒸（episode 改补一张空章）。run 的 `run_done` 组装 `RunResp`、写 `run_end`。
- **入口**（`run_entry` / `episode_entry` / `task_entry`）：装初值，**不取帧**；episode / task 的入口写
  `*_start`，run 的 `run_start` 在图内 `begin`。`run_entry.new_run` 只写它亲手接住的 `run_error`。

## 二、层间交接（IO 契约）

| 方向 | 模型 | 字段 |
|---|---|---|
| run → episode | `EpisodeInput` | `run_id`、`episode_id`、`goal`（`Task`，`max_steps` = task 数上限） |
| episode → run | `EpisodeOutput` | `episode_id`、`goal_id`、`termination`、`judge_reason`、`reason`、`tasks_used`、`acts_used`、`observation`（终局帧，run 判世界结束用）、`memory` |
| episode → task | `TaskInput` | `run_id`、`episode_id`、`task`（`max_steps` = 键数上限）、`start_step`（本局键号基数，**唯一来源**） |
| task → episode | `TaskOutput` | `task_id`、`termination`、`judge_reason`、`reason`、`steps_used`、`memory` |

`termination` ∈ `goal_done` / `world_ended` / `stalled` / `budget_exhausted` / `error`。两个 `*Output`
的 `success` 是由它推出的只读属性（`Settled`），不存。

**两种"理由"分开**：`judge_reason` 是 `review_and_judge` 写的**判定依据**（为什么判停 / 为什么判成），
`reason` 是 `*_done` 里 LLM 看完下级记录写的**结论说明**（停在哪、差在哪）。蒸馏时 `judge_reason`
作为参考素材给到 LLM，但 `reason` 不照抄它。run 层没有 `*_done` 的蒸馏，所以只有 `judge_reason`。上层不向下层传帧，下层也不回传帧给上层用。

### 各层的机械三类

| 层 | 世界终局 | 停滞 | 预算 |
|---|---|---|---|
| run | 上一局 `observation.done` | `fail_streak ≥ RUN_STALL_LIMIT`(3) | `step ≥ RUN_MAX_EPISODES`(50) |
| episode | 本圈帧 `observation.done` | `fail_streak ≥ EPISODE_STALL_LIMIT`(3) | `step ≥ goal.max_steps`（task 数） |
| task | 本圈帧 `observation.done` | `stall_count ≥ ACT_STALL_LIMIT`(5) | `step ≥ task.max_steps`（键数） |

每层**独立计数**。`fail_streak` 按机器结算先记，人审推翻时由盖章处修正。

## 三、每层的数据流

### run

```
begin ─► perceive[absorb_episode → read_plan_context]
      ─► review_and_judge[定案上一局（盖章 → 人审 → settle_goal） → 机械三类 → judge]
      ─► (done → run_done) | plan_run[Planner → 目标表更新] ─► act[dispatch → run_episode] ─► perceive
```

- 目标表 `goals: list[GoalEntry]`（`task` / `status` / `attempts` / `last_episode_id` / `note` / `overturned`）。
- 失败的目标盖 FAILED，不自动重派；planner 可把它重开成 PENDING。
- 起止账在图内：`begin` 写 `run_start`，`run_done` 写 `run_end`。
- episode 子图抛错由 `act` 接住：补空章 → 记 `episode_error`；`AgentError` 兜成 `termination=error`
  的结算送回 perceive，别的异常原样上抛、由 `new_run` 记 `run_error`。

### episode

```
begin_episode ─► perceive[absorb_task → sense（完整档）→ retrieve_task_memories
                          → retrieve_global / knowledge / object → merge_retrieval]
              ─► review_and_judge[定案上一个 task（盖章 → 人审 → 失败则放弃剩余 PENDING → settle_task）
                                  → 机械三类 → judge(goal × 任务表 × TaskMemory)]
              ─► (done → episode_done) | plan_episode[没有 PENDING 才拆 → 追加新一版] ─► act[run_task] ─► perceive
episode_done = verify_task_memories → summarize_episode → close_episode
             （没有 TaskMemory 时：leave_chapter → close_episode）
```

- 任务表 `tasks: list[TaskEntry]`（`task` / `status` / `note` / `overturned` / `round`）。task 只派一次；
  定案失败后同一版剩下的 PENDING 标 ABANDONED，下一圈 decomposer 看着表、从当前画面重拆，
  新条目追加进表（`round` +1，`task_id` 接着往下数）。
- task 子图抛错由 `act` 接住：记 `task_error`；`AgentError` 兜成 `termination=error` 的 `TaskOutput`
  （`steps_used` 从账上数这个 task 已按的键），下一圈照常定案成 FAILED、放弃同版剩余 PENDING、重拆。
- 拆解要求：每个 task 只靠 RAM 观测（坐标、对话、选项、光标、排布）加固定动作空间即可完成。

### task

```
begin_task ─► perceive[sense（RAM 档）→ detect_stall → store_step_episode_memory
                       → store_object_semantic_memory → close_step → retrieve_act_memories → get_action_space]
           ─► review_and_judge[机械三类 → judge(task × 本 task 最近几条 ActMemory)]
           ─► (done → task_done) | plan_task[Chooser → 首段 times=1] ─► act[按键, step+1] ─► perceive
task_done = verify_act_memories → summarize_task → close_task
```

- `sense` 每圈都取帧（步号 = `start_step + step`）；中间三个单元只在上一圈按过键时写
  （停摆、ActMemory、物件事件）；`close_step` 把新帧转正（上一圈按过键才记 `advance_step`）。
- 帧槽只由 task 的 `sense` 写、只由 `store_step_episode_memory` 读（ActMemory 的前后两张图）。

### 记忆阶梯

`ActMemory`（task.perceive 每键写，带 `task_id`）→ `TaskMemory`（task_done 写）→ `EpisodeMemory`
（episode_done 写；没有 TaskMemory 的局由 `leave_chapter` 补空章，整局异常的局由接住它的 run `act`
代补）。**每层的记忆只由本层写**：run 层不写任何记忆。每层 perceive 只读直属下一级：
task 读本 task 的 ActMemory，episode 读本局的 TaskMemory，run 读 EpisodeMemory。记忆的章保留
机器判定（`termination`），**定案以表为准**。

## 四、事件总表

`kind` 是 `TraceKind` 的值，`type` 是 `EventType` 之一；producer = `meta.source`。

**命名规则（204）**——请求与结论、写账的位置逐一对得上：

| 族 | 规则 | 成对 |
|---|---|---|
| 模型交互 | `<链路>_call` ↔ 它的结论账；链路名 = `link` 的值 | `sense_call`↔`sense_frame`、`choose_call`↔`choose_verdict`、`plan_call`↔`plan_verdict`、`decompose_call`↔`decompose_verdict`、`judge_call`↔`judge_verdict`、`verify_call`↔`verify_verdict`、`summarize_task_call`↔`write_task_memory`、`summarize_episode_call`↔`write_episode_memory` |
| 记忆 | `read_<记忆全名>` / `write_<记忆全名>` | act_memory / task_memory / episode_memory / object_memory / knowledge |
| 动作 | 动词在前 | `press_key`、`check_stall`、`advance_step`、`get_action_space` |
| 生命周期 | `<层>_start` 在该层入口、`<层>_end` 在该层 `*_done`、`<层>_error` 由**接住异常的那一格**记 | task_error ← episode `act`；episode_error ← run `act`；run_error ← `new_run` |
| 定案 | `settle_<表>` | `settle_goal`（run 目标表）、`settle_task`（episode 任务表） |
run / task 两层的同名格用 `run.` / `task.` 前缀区分（episode 层不加前缀）。

**生命周期**

| kind | type | producer | `content` |
|---|---|---|---|
| `run_start` | lifecycle | `run.begin` | `goals`、`success_criteria`、`run_goal`、`run_criteria` |
| `run_end` | lifecycle | `run_done` | `total`、`succeeded`、`termination`、`judge_reason` |
| `run_error` | lifecycle | `run_entry.new_run` | `error` |
| `episode_start` | lifecycle | `episode_entry.begin_episode` | `goal_id`、`goal`、`success_criteria`、`max_steps` |
| `episode_end` | lifecycle | `close_episode` | `termination`、`judge_reason`、`tasks_used`、`acts_used`、`reason` |
| `episode_error` | lifecycle | `run.act` | `error` |
| `task_start` | lifecycle | `task_entry.begin_task` | `goal`、`success_criteria`、`max_steps`、`start_step` |
| `task_end` | lifecycle | `close_task` | `termination`、`judge_reason`、`steps_used`、`reason` |
| `task_error` | lifecycle | `episode.act` | `error` |
| `settle_goal` | lifecycle | `run.review_and_judge` | `goal_id`、`status`、`episode_id`、`attempts`、`audit`、`note`、`overturned`、`fail_streak` |
| `settle_task` | lifecycle | `review_and_judge` | `task_id`、`status`、`round`、`audit`、`note`、`overturned`、`abandoned`（数组）、`fail_streak` |
| `advance_step` | lifecycle | `close_step` | `next_step` |
| `review_inject` | lifecycle | 插话点：`plan_run` / `plan_episode` / 两层 `review_and_judge`（`harness/reviewing.py`，每问一轮一条） | `form_kind`、`reply`（空串 = 没意见） |
| `review_audit` | lifecycle | 审：两层 `review_and_judge` 的定案 | `verdict`、`note` |
| `checkpoint_save` | lifecycle | `checkpoint.save`（run 开局 / 每局开派前） | `checkpoint_id`、`level`、`manifest_path` |
| `checkpoint_restore` | lifecycle | `checkpoint.restore`（新执行线第一条；回放时在目标 task 开局前） | `checkpoint_id`、`level`、`parent_branch`、`parent_last_event_uuid`、`to_task` |
| `world_snapshot` | lifecycle | `checkpoint.save`（每个 task 开局，`meta.task_id` 为该 task） | `path` |
| `trace_sealed` | lifecycle | `checkpoint.save`（一局结束 / run 出错） | `checkpoint_id`、`count` |

**模型调用账（`model_call`）**：正文是那次调用原样（`ok`/`prompt`，成功另带 token 与 `raw`）

| kind | producer |
|---|---|
| `plan_call` | `plan_run` |
| `decompose_call` | `plan_episode` |
| `choose_call` | `plan_task` |
| `judge_call`（+`why`） | 三层 `review_and_judge` |
| `verify_call`（+`verdicts`） | `verify_act_memories` / `verify_task_memories` |
| `summarize_task_call` | `summarize_task` |
| `summarize_episode_call` | `summarize_episode` |
| `sense_call` | episode 的 `sense`（完整档才调视觉模型） |

**结论账（`llm_outcome`）**：带 `input`/`output`（成功那次的请求与原文）

| kind | producer | `content` |
|---|---|---|
| `plan_verdict` | `plan_run` | `pushed_goals`、`updates`、`why`、`human_note` |
| `decompose_verdict` | `plan_episode` | `tasks`（`task_id`/`goal`/`success_criteria`/`max_steps`）、`why`、`human_note` |
| `choose_verdict` | `plan_task` | `sequence`、`thought` |
| `judge_verdict` | 三层 `review_and_judge` | `termination`、`fail_streak`、`judge_reason`、`human_note` |
| `verify_verdict` | `verify_act_memories` / `verify_task_memories` | `checked`、`negative` |

**观测 / 动作**

| kind | type | producer | `content` |
|---|---|---|---|
| `sense_frame` | view | episode 的 `sense`（完整档）/ `task.sense`（RAM 档） | `status`、`facts`、`done`、`perceived`、可选 `place` / `frame` |
| `get_action_space` | act | `get_action_space` | `names` |
| `press_key` | act | `act`（task） | `sequence`（单段） |
| `check_stall` | act | `detect_stall` | `stall_key`、`stall_count` |

**记忆读写（`memory_io`）**：读账统一 `query` + `refs`；写账正文就是记录本体（去坐标与来源章）

| kind | producer |
|---|---|
| `read_act_memory` | `retrieve_act_memories`（task.perceive，按 `episode_id + task_id` 查） |
| `read_task_memory` | `retrieve_task_memories`（episode.perceive） |
| `read_episode_memory` | `retrieve_global_episode_memory`、`run.perceive`（`order_by=episode_id`）、`leave_chapter` / `run.act`（补空章前先查） |
| `read_knowledge` | `retrieve_knowledge_semantic_memory` |
| `read_object_memory` | `retrieve_object_semantic_memory`、`run.perceive`（`refs` 为唯一键 `(ep, step, place.key)`） |
| `write_act_memory` | `store_step_episode_memory` |
| `write_object_memory` | `store_object_semantic_memory` |
| `write_task_memory` | `summarize_task` |
| `write_episode_memory` | `summarize_episode`（正文版）/ `leave_chapter`、`run.act`（空章版） |

存档与问人的账不进 `node_io` 的活动流（旁路；条数随存档开关、人插话几轮浮动）。`checkpoint_error`（type `error`：`checkpoint_id`/`stage`/`error`）存档失败时记。

**错误**：`call_failed`（由 `model_call` 连带产出：`link`/`exception`/`reason`）、
`call_exhausted`（各调用点：`link`）、`summary_parse_error`（`link` ∈ `summarize_episode` / `summarize_task`、`reason`；
蒸馏链"答了但解析不了"时由 `model_call` 连带产出，取代那次的 `call_failed`）。

## 五、正文编码约定

一条落盘事件六个字段（`uuid` / `kind` / `type` / `ts` / `meta` / `content`），`meta` 与 `content` 都是 JSON 字符串。

- **`meta` 恰好六件**：`run_id` / `branch` / `source` / `episode_id` / `task_id` / `step`（`run_id`、`branch` 由落盘层盖；`branch` 未经恢复为 `main`，见 `docs/checkpoint/spec.md`）。
  上层的空槽填本层自己的 id（run 级账 `episode_id = task_id = run_id`；episode 级账 `task_id = episode_id`）；
  run 级 `step` = 已派局数；episode 级与 task 级 = 本局当前键号（同一局里两层共用一条键号轴）。
- **顺序只认 `(ts, uuid)`**，磁盘账本是唯一真相。
- **标量一律 `str()`，布尔一律小写**（`done` / `ok` / `perceived` / `overturned`）。
- **结构化数据直接放对象 / 数组**（`facts` / `sequence` / `verdicts` / `refs` / `names` / `goals` / `tasks` /
  `abandoned` / 写账正文），不双重编码。
- **能推出来的不写**：`success` / `done` 由 `termination` 推出，结算账里不记；`task_id` 在 `meta` 上的，正文不重复。
- **写账正文 = 记录本体去坐标与来源章**：`_STEP_BODY_DROP`、`_TASK_BODY_DROP`、`_EPISODE_BODY_DROP`。
- **画面真源在 ActMemory 的 `before_frame` / `after_frame`**；`sense_frame` 的 `frame` 是另一份，没有就省略这个键。

## 六、核对与已知缺口

- **逐格核对**在 `experiment/real_check/node_io.py`：按 `meta` 把账切成 run / episode / task 三种流，
  每种流用一张后继表（就是那张图的拓扑）核执行序，再核层间计数与盖章。样本见 `tests/_fake_run.py`。
- **`sense_call` 在假样本里碰不到**（假世界不产调用账），它的正文只由账单契约核。
- **`MemoryToolPort.query_recent_act_memories` 已无 harness 调用方**（task 层改读 `task_ctx.act_memories`），
  只剩 `check_memory_roundtrip` 在用。
