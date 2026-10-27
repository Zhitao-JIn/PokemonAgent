# spec —— 评测时冻结规划层

> 版本 v1。依据：`docs/eval_freeze/intent.md`。基线：主线 `e7155c3d922f28e92289e3deacf4f4fb02ad6582`。
> 本 spec 里的函数与行为均由设计侧读代码核实；"待执行方核实"的项在对应检查点先核实，与此处不符就停下汇报。

## 一、决定表

| 编号 | 决定 | 取舍 |
|---|---|---|
| D1 | 开关放 `LoopConfig`（`pokemon_agent/settings/schema/loop.py`）与 `settings/default.json`：`freeze_run_plan: bool`、`freeze_episode_plan: bool`，默认 `false` | 与现有 `plan_max_new_goals` 同段；评测按样本覆盖配置即可，不新增入口 |
| D2 | 冻结的 run 层行为：`plan_run` 入口直接返回，不调用 `planner.plan`、不问 reviewer、不写 `PLAN_CALL` / `PLAN_VERDICT`、不占 `planning_rounds_used`。判负规则：表中任一条目状态为 `FAILED` 或 `ABANDONED` 时，立即 `stopped_updates(..., Termination.FROZEN_ITEM_FAILED)`，不继续派发后面的条目；否则有 `PENDING` 条目时返回 `judge_trigger="normal"` 并走 `act`，没有时 `stopped_updates(..., Termination.PLANNING_EXHAUSTED)` | 冻结层不允许上层改动，也不允许重试，失败即样本失败；代价是新增一个枚举值 |
| D3 | 冻结的 episode 层行为同 D2：`plan_episode` 入口直接返回，不调 decomposer、不问 reviewer、不写 `DECOMPOSE_*` 账、不占 `decompositions_used`；task 表中任一条目为 `FAILED` / `ABANDONED` 时以 `Termination.FROZEN_ITEM_FAILED` 收尾；无 `PENDING` task 时以 `Termination.DECOMPOSITIONS_EXHAUSTED` 收尾 | 同 D2 |
| D4 | 冻结 task 表放 `GoalEntry.frozen_tasks: list[Task]`（默认空列表），`dispatch.py` 把它带进新字段 `EpisodeInput.tasks: list[Task]`（默认空列表），`begin_episode` 用它装初始 `state.tasks`（每条 `TaskEntry`，`round=1`，`PENDING`）并给出初始 `execution_order` | 状态进 `RunState`，可随 checkpoint 恢复；代价是 `state_schema_hash` 变化 |
| D5 | 冻结的 task 表条目复用 `Task` 模型（`task_id`、`goal`、`success_criteria`、`max_steps`），`task_id` 由样本给出，必须在同一 episode 内唯一 | 不新增模型 |
| D6 | `freeze_episode_plan` 开启但 `EpisodeInput.tasks` 为空：`begin_episode` 抛断言错误（前置条件违反），不静默退化为自由规划 | 数据错误显式暴露 |
| D7 | `freeze_run_plan` 开启但初始目标表为空：`new_run` 断言失败 | 同上 |
| D8 | 评测样本契约新增 `tier: Literal["short","mid","long"]`（默认 `"long"`，与现有行为一致）与 `goals: list[SampleGoal]`（默认空）；`SampleGoal` 含 `goal`、`success_criteria`、`max_steps`、`tasks: list[SampleTask]`（`SampleTask` 含 `goal`、`success_criteria`、`max_steps`）。`tier="mid"` 要求 `goals` 非空且 `tasks` 全空；`tier="short"` 要求 `goals` 恰一条且 `tasks` 非空；`tier="long"` 要求 `goals` 为空 | 档位与冻结层一一对应，加载时校验 |
| D9 | `one.py` 按档位组装：`long` 传空目标表 + run goal（现状）；`mid` 传 `goals` 目标表 + `freeze_run_plan=true`；`short` 传单条带 `frozen_tasks` 的目标 + `freeze_episode_plan=true` 与 `freeze_run_plan=true`（run 层只有这一个目标，不再规划）。开关经样本级配置覆盖传入，不改全局默认 | 短期也冻结 run 层，避免 plan·L0 在单目标样本上自由改写 |
| D10 | 冻结模式下 `run_goal` 仍显式传入（样本的 `goal`）；目标表条目的 `task_id` 取样本 `sample_id` 加序号（如 `<sample_id>-g1`），`task` 的 `task_id` 同理（`<sample_id>-g1-t1`） | 与 run-goal-split 的归属键约定一致（按 `run_id`，不按目标 id） |

## 二、检查点

| 检查点 | 内容 | 验收核对点 |
|---|---|---|
| CP1 run 层冻结 | D1、D2、D7：配置字段与默认值、`Termination.FROZEN_ITEM_FAILED`、`plan_run` 冻结分支、`new_run` 断言、路由确认；测试用手写 planner 替身，断言冻结时零调用 | 开关关时现有测试全绿且行为不变；开关开时 planner 替身调用次数为 0；表序与派发顺序一致；任一条判负立即以 `FROZEN_ITEM_FAILED` 收尾且后面的条目没有被派发；表耗尽走 `PLANNING_EXHAUSTED` |
| CP2 episode 层冻结 | D3–D6：`GoalEntry.frozen_tasks`、`EpisodeInput.tasks`、`dispatch`、`begin_episode`、`plan_episode` 冻结分支；`state_schema_hash` 变化的同步 | decomposer 替身零调用；task 数与表序一致；任一 task 判负立即以 `FROZEN_ITEM_FAILED` 收尾；空 `tasks` + 开关开 → 断言失败；`state_schema_hash` 变化已记录在 CHANGELOG 条目 |
| CP3 评测接线 | D8–D10：`EvalSample` 字段与加载期校验、`one.py` 组装、样本级配置覆盖；`dataset/build/preconditions.py` 不动；新增校验测试与组装测试（不跑真实模型） | 三档样本各一条构造用例通过；非法组合在加载时报 `DatasetError`；`long` 档行为与现状完全一致 |

## 三、文件改动清单（允许范围）

- CP1：`pokemon_agent/settings/schema/loop.py`、`pokemon_agent/settings/default.json`、`pokemon_agent/harness/run/plan_run/plan_run.py`、`pokemon_agent/harness/run/run_entry.py`、对应测试（`tests/harness/`、`tests/settings/` 下新增或修改）、`CHANGELOG.md`。
- CP2：`pokemon_agent/schemas/harness/domain/goal_entry.py`、`pokemon_agent/schemas/harness/domain/episode_io.py`、`pokemon_agent/harness/run/act/dispatch.py`、`pokemon_agent/harness/episode/episode_entry.py`、`pokemon_agent/harness/episode/plan_episode/plan_episode.py`、对应测试、`CHANGELOG.md`；若 `state_schema_hash` 的测试夹具需同步，仅限这些夹具文件。
- CP3：`evals/agent_short_goal_run/dataset/schemas.py`、`evals/agent_short_goal_run/dataset/loader.py`、`evals/agent_short_goal_run/solver/runner/one.py`、对应测试、`CHANGELOG.md`。
- 路径以 `pokemon_agent/harness/run/run_entry.py` 的 `new_run` 为准核实；若某文件不存在或函数名不同，停下汇报。

## 四、待执行方先核实的事项（动手前必须核）

1. `planning_route`（`pokemon_agent/harness/planning.py`）在 `plan_run` / `plan_episode` 冻结返回后的路由：有 `PENDING` 走 `act`，无则回 `review_and_judge`；冻结的"无待办且未判成功"必须收尾而不是死循环。
2. 读侧是否假设每个 run / episode 都有 `PLAN_CALL`、`PLAN_VERDICT`、`DECOMPOSE_CALL`、`DECOMPOSE_VERDICT`：检索 `evals/agent_short_goal_run/scorer/`、`pokemon_agent/reviewer*`、`pokemon_agent/trace`、`summarize_run`；发现依赖就停下汇报，不自行改读侧。
3. `execution_order` 在初始非空目标表下由谁初始化（`new_run` 或 `plan_run`），冻结时是否还需要 `apply_planning`。
4. 评测样本级配置覆盖（`build_real(config=[run_config_path, sample_config])`）能否覆盖 `loop` 段的两个新字段。

## 五、测试清单

- CP1：冻结关→现有测试不变；冻结开→planner 替身 0 次调用、派发顺序等于表序、第一条判负后第二条不派发且类别为 `FROZEN_ITEM_FAILED`、耗尽收尾类别为 `PLANNING_EXHAUSTED`；空表 + 冻结开→断言。
- CP2：冻结开→decomposer 替身 0 次调用、task 顺序等于表序、第一个 task 判负后第二个不派发且类别为 `FROZEN_ITEM_FAILED`、耗尽类别为 `DECOMPOSITIONS_EXHAUSTED`；`tasks` 为空 + 冻结开→断言；冻结关且 `tasks` 非空→忽略 `tasks` 的行为须在测试里钉死（默认走自由规划，不使用它）。
- CP3：三档各一条合法样本加载通过；`mid` 带 `tasks`、`short` 无 `tasks`、`long` 带 `goals` 三种非法组合各报 `DatasetError`；`one.py` 组装对三档产出的 `new_run` 入参与配置覆盖逐项断言（用替身 harness，不启动模拟器）。

## 六、验证方式

不调用真实模型，不启动模拟器。全部用手写替身。

## 七、停止条件

遇到下列任一情形停下汇报，不要重试、不要绕过：改动超出允许文件范围；起点不是全绿；读侧依赖被冻结跳过的账（核实项 2）；`planning_route` 在冻结下会死循环；`state_schema_hash` 变化（含新增 `Termination` 枚举值）导致 checkpoint 相关测试需要改动允许范围外的文件；需要执行被禁止的 git 命令；任何真实模型调用。

## 八、非目标

不动 prompt；不动 judge 与 review 的判定逻辑；不改机械判据；除 `FROZEN_ITEM_FAILED` 外不新增 Termination 枚举值；不做长期样本；文档（AGENTS.md、CLAUDE.md、`docs/`）的同步另案处理。
