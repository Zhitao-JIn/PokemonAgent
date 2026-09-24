# harness —— 模块规格

> 最后更新：2026-09-24（CHANGELOG 195–203）｜ 活文档：与代码冲突时以代码为准。
> 端到端数据流与事件总表见 [`../DATAFLOW.md`](../DATAFLOW.md)，图见 [`../diagrams/`](../diagrams/)。

## 一、职责与边界

`pokemon_agent/harness/` 是控制循环本体：用**三张同构的 LangGraph 图**承载 run（一整轮游戏）、
episode（一个目标）、task（目标拆出的一个小任务），也是**全项目唯一写 trace 的地方**。

- **分层**：harness 只依赖 `tools` / `schemas` / `prompts`，写账只经 `TraceToolPort.append`，读账只经 `read_events`。
- **三张图各有一个状态载体**：`RunState` / `EpisodeRunState` / `TaskState`，只放可 JSON 化的数据。
- **三个 runtime 装活对象**：`RunRuntime ⊃ EpisodeRuntime ⊃ TaskRuntime`，嵌套持有；`trace` / `memory` /
  `reviewer` / `game` 是同一实例的引用。唯一装配点是 `pokemon_agent/build.py::build_real`。
- **父图调子图的方式（形态 B）**：父层 `act` 调子层入口 `run_*`，入口里 invoke 子图并交回 `*Output`。
  父子之间只经 `EpisodeInput/Output`、`TaskInput/Output` 交接，不共享 state。

## 二、目录结构

```
harness/
├── __init__.py  compose.py（compose_units：格内单元串接）  judging.py（三层共用的停判）
│                sensing.py（perceive_once：向世界取一帧的唯一入口）
├── interface/   reviewer.py（Reviewer 协议） planner_outcome.py（PlannerOutcome / GoalUpdate）
├── console_reviewer.py  file_reviewer.py  null_reviewer.py
├── run/
│   ├── harness.py（RunHarness） run_entry.py（new_run / close） run_graph.py run_state.py runtime.py
│   ├── begin/  perceive/{absorb_episode, read_plan_context}  review_and_judge/
│   └── plan_run/  act/{dispatch}  run_done/
├── episode/
│   ├── episode_entry.py（begin_episode / run_episode / close） episode_graph.py episode_state.py episode_runtime.py
│   ├── perceive/{absorb_task, sense, retrieve_task_memories, retrieve_global_episode_memory,
│   │             retrieve_knowledge_semantic_memory, retrieve_object_semantic_memory, merge_retrieval}
│   ├── review_and_judge/  plan_episode/  act/
│   └── episode_done/{verify_task_memories, summarize_episode, close_episode}
└── task/
    ├── task_entry.py（begin_task / run_task / close） task_graph.py task_state.py task_runtime.py frames.py
    ├── perceive/{sense, detect_stall, store_step_episode_memory, store_object_semantic_memory,
    │             close_step, retrieve_act_memories, get_action_space}
    ├── review_and_judge/  plan_task/  act/
    └── task_done/{verify_act_memories, summarize_task, close_task}
```

**格 = 文件夹**：图上一个节点是一个文件夹，格内多个单元由 `compose_units` 按序串接，顺序是契约。

## 三、三张图

三张图同一骨架：

| 边 | 类型 | 判据 |
|---|---|---|
| `perceive → review_and_judge` | 直边 | — |
| `review_and_judge → *_done` / `plan_*` | 条件边 | `state.done` |
| `plan_* → act` | 直边 | — |
| `act → perceive` | 直边 | — |
| `*_done → END` | 直边 | — |

run 图另有 `START → begin → perceive`（`begin` 校验目标表、写 `run_start`）。episode / task 图的开局在入口
（`begin_episode` / `begin_task`：写 `*_start`、装初值，**不取帧**）里做，图从 `perceive` 起。

**下层抛错由上层的 `act` 接住**（谁接住谁记账）：episode 的 `act` 接 task 抛错 → 记 `task_error`；run 的
`act` 接整局抛错 → 补空章、记 `episode_error`。`AgentError` 兜成 `termination=error` 的 `*Output` 交给下一圈
perceive（这一局 / 这一 run 照常往下走），别的异常记完原样上抛，最终由 `run_entry.new_run` 记 `run_error`。

**每层 perceive 的三件事**：吸收下层结算 → 取帧（episode 完整档、task RAM 档、run 不取）→
读直属下一级的记忆与世界事实。本层其余各格只用 perceive 装好的上下文，不自己查库。

| 层 | plan 格做什么 | act 格做什么 | 收尾 |
|---|---|---|---|
| run | `plan_run`：Planner 更新目标表（新增 / 定点改状态），没 PENDING 时抛 `NoGoalToDispatch` | `dispatch` 标 RUNNING + 造 `EpisodeInput` → `run_episode`（接住整局抛错） | `run_done`：组装 `RunResp`、写 `run_end` |
| episode | `plan_episode`：任务表没有 PENDING 时 Decomposer 拆下一版，追加进表 | 第一条 PENDING 标 RUNNING → `run_task`（接住 task 抛错） | verify → summarize → close（素材是 `ep_ctx.task_memories`；没有时 leave_chapter 补空章 → close） |
| task | `plan_task`：Chooser 选一段按键，只执行首段 `times=1` | 按键、`step+1` | verify → summarize → close（素材是 `task_ctx.act_memories`） |

**停判只在 `review_and_judge`**：先 `mechanical_termination`（世界终局 / 停滞 / 预算，阈值见 DATAFLOW 二），
不中再 `ask_judger`；judge 说 done 即 `GOAL_DONE`。写 `termination`（`done` / `success` 由它推出，`Settled`）
与 `judge_reason`（`judging.judge_reason()`：判成时是判定员的理由，机械判停时是"机械判停：<类别>；<判定员的话>"）。
`reason` 不在这里写，它是 `*_done` 里 LLM 的结论。
run 与 episode 这一格还负责**定案上一条**（`_settle`）：盖章 → 人审（推翻则盖反面、`overturned=True`、
修正 `fail_streak`）→ 记 `settle_goal` / `settle_task`。episode 定案为失败时，把同一版剩下的 PENDING
标 ABANDONED。**每层的记忆只由本层写**：run 不写记忆，"一局一条 EpisodeMemory"由 episode 层自己保证。

## 四、状态模型

| 字段 | `RunState` | `EpisodeRunState` | `TaskState` |
|---|---|---|---|
| 身份 | `run_id`、`run_goal` | `run_id`、`episode_id`、`goal` | `run_id`、`episode_id`、`task`、`start_step` |
| 本层计数 | `step`（已派局数） | `step`（已派 task 数）、`total_acts` | `step`（本 task 已按键数；帧步号 = `start_step + step`） |
| 失败计数 | `fail_streak` | `fail_streak` | `stall_key`、`stall_count` |
| 表 | `goals`（`GoalEntry`） | `tasks`（`TaskEntry`） | — |
| 上下文 | `plan_ctx`（局索引 / 详情 / 物件） | `ep_ctx`（帧 / TaskMemory / 跨局摘要 / 知识 / 物件） | `task_ctx`（帧 / ActMemory / 动作空间）、`action` |
| 下层交回 | `pending_episode` → `episode_outputs` | `pending_task` → `task_outputs` | `after_observation`（格内流转） |
| 终局 | `termination`、`judge_reason` | 同左 + `task_verdicts`、`reason`、`memory`、`output` | 同左 + `act_verdicts`、`reason`、`memory`、`output` |

**跨圈传递**：父层 `act` 只写 `pending_*`；下一圈的 `perceive`（`absorb_*`）把它并入本层状态并清掉，
`review_and_judge` 据最终定案改表。三层 state 都混入 `Settled`，`done` / `success` 是只读属性。

## 五、依赖注入面

| runtime | 字段 |
|---|---|
| `RunRuntime` | `trace`、`memory`、`reviewer`、`planner`、`judger`、`episode` |
| `EpisodeRuntime` | `game`、`memory`、`decomposer`、`judger`、`verifier`、`summarizer`、`trace`、`reviewer`、`task` |
| `TaskRuntime` | `game`、`chooser`、`judger`、`memory`、`reflector`、`verifier`、`task_summarizer`、`trace`、帧槽 `frame_before`/`frame_after` |

能力对象来自 `tools/brain_tool.py`，`build.py` 按层各造一份 brain（`run_brain` / `episode_brain` / `task_brain`）。

## 六、人在环

`Reviewer`（`interface/reviewer.py`）：`inject(req) -> str`（插话，空串 = 没意见）与 `audit(req)`（审，恒返回表态）。

| 实现 | 适用 |
|---|---|
| `NullReviewer` | 无头：不插话、不推翻 |
| `ConsoleReviewer` | 同一终端：超时 `CONSOLE_REVIEW_TIMEOUT` |
| `FileReviewer` | 驱动方无终端：请求 / 回应走盘上文件；`audit()` 恒认账 |

- **插话点**：`plan_run`、`plan_episode`、`plan_task`、三层 `review_and_judge`。不满意就带着那句话重问，插话进 `human_note` 落账。
- **审点**：run 与 episode 的 `review_and_judge._settle`（给上一局 / 上一个 task 盖章前）。审核请求装
  `outcome`（`EpisodeOutput` 或 `TaskOutput`）与被审对象自己的 trace；推翻会调整 `fail_streak`、标 `overturned`，
  结果进 `settle_goal` / `settle_task` 的 `audit`。**定案以表为准**，记忆的章保留机器判定。

## 七、trace 写入

- `meta` 恰好五件：`run_id` / `source` / `episode_id` / `task_id` / `step`；上层空槽填本层自己的 id。
- `kind` 词表：`schemas/harness/domain/trace_kind.py::TraceKind`；`type` 7 类：`model_call` / `error` /
  `llm_outcome` / `view` / `act` / `memory_io` / `lifecycle`。
- 逐 kind 的 producer 与正文字段见 [`../DATAFLOW.md`](../DATAFLOW.md) 第四节。
- 起止账：`run_start` 在 `run.begin`、`run_end` 在 `run_done`；`episode_start` / `task_start` 在入口、
  `episode_end` / `task_end` 在 `close_*`；`*_error` 由接住异常的那一格记（见第三节）。
- 不写账的单元：`merge_retrieval`、`dispatch`；run / episode 的 `act` 只在下层抛错时发账。

## 八、已知缺口

- **`FileReviewer.audit()` 恒认账**：推翻只能经 `ConsoleReviewer`；它在每局、每个 task 结束时都会停下等人
  （最多 `CONSOLE_REVIEW_TIMEOUT` 秒，超时按认账）。
- **图形状的守卫**：`experiment/real_check/node_io.py` 按层切流、用后继表核三张图的执行序；
  `tests/test_node_io.py` 用 `tests/_fake_run.py`（假大脑跑真图）做正反例。
