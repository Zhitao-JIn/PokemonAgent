# run goal 与可编辑目标表分离 —— spec

版本 v1（2026-10-24）。依据：`docs/run-goal-split/intent.md`（已确认）。基线：主线 fa10d49。

## 决定表

| 编号 | 决定 | 取舍 |
|---|---|---|
| D1 | run 粒度样本的“目标局”= 本执行线上全部 `episode_start` 的 `episode_id`（按开局先后、去重）；episode / task 粒度仍用 `episodes_for(sample_id)`。 | 只改取局口径，不加血缘字段；run 内只有一个 run goal，`run_id` 即归属键，分支过滤已由 `RunStream.load` 完成（`stream.py:130-141`）。 |
| D2 | 取局口径收敛为一个函数 `target_episodes(stream, sample) -> list[str]`（放 `scorer/utils.py`），`registry.judge` 的闸门、`target_frames`、`rules/shop.py` 三处全部改用它。 | 避免再出现一处直接调 `episodes_for(sample.sample_id)`；`episodes_for` 保留给 episode / task 粒度。 |
| D3 | `RunHarness.run(run_id, goals, run_goal=None, *, start_task=None, checkpoint_only=False, sample_id="")`：`goals` 可为空列表。`goals` 为空时 `run_goal` 必给（assert）；`goals` 非空且 `run_goal` 缺省时行为与现在完全一致（`default_run_goal`）。 | 其余调用方（`evals/dataset/brain_choose/build/collect.py:77`、各测试）无需修改。 |
| D4 | 世界 reset 的 Task：`start_task` 给了用它；否则 `goals` 非空用 `goals[0]`；否则用 `start_task_for(run_id, run_goal)` 合成：`Task(task_id=run_id, goal=run_goal.goal, success_criteria=run_goal.criteria, max_steps=1)`。`start_task_for` 住 `run_entry.py`，`checkpoint/restore.py` 复用。 | `pyboy_world.reset` 只存下 Task 做断言（`pyboy_world.py:113`），`ports.py:210` 要求 `max_steps > 0`，故合成值取 1。`initial_state_hint` 只能由调用方经 `start_task` 带入。 |
| D5 | `begin` 去掉“目标表非空”的断言，保留“至多一条 RUNNING”。`run_entry.new_run` 去掉 `assert goals`，改为“`goals` 与 `run_goal` 至少给一个”。 | 空表是正常调度起点：首圈 `plan_run` 先于 `act` 执行（`run_graph.py:59-70`），planner 无新增时回 `review_and_judge` 并带 `judge_trigger="no_pending"`（`planning.py:56-64`）。 |
| D6 | 评测入口 `one.py` 改为：`harness.run(run_id, [], run_goal=Goal(goal=sample.goal, criteria=sample.success_criteria), start_task=_task_for(sample), sample_id=sample.sample_id)`。预检路径（`one.py:61-68`）仍用 `_task_for`。 | 种子条目消失，样本 id 不再充当目标 id。 |
| D7 | 不改 `RunState` 字段、不改 `run_plan` prompt、不改 `review_and_judge`。`state_schema_hash()`（`harness/checkpoint/manifest.py:105`）改动前后必须相同。 | 避免触发存档重打。 |
| D8 | 641更新：sample.max_steps只用于种子Task与world reset，不约束第一局。planner的budget.limit仅建议；episode_max_tasks、task_max_steps、max_episodes及规划轮数等配置控制硬限。loop.plan_max_new_goals仅是单版新增建议量。 | 见[父级建议与配置硬预算](../budget/ADVISORY_AND_HARD_LIMITS.md)；新代码需重新冻结基线，历史评测不重评。 |
| D9 | ROADMAP 占位：`docs/ROADMAP.md` 的 E 类总览表加一行 E8，第四节加 E8 详述条目，状态 📋，沿用 E7 的格式。 | 只占位，不承诺实现。 |

## 检查点

### CP1 评分按 run 取局（CHANGELOG 633）

- 改动：`scorer/utils.py` 新增 `target_episodes`；`target_frames` 与之统一；`scorer/registry.py` 闸门改用它；`scorer/rules/shop.py` 三处（原 70、105、167 行）改用它；必要时 `scorer/stream.py` 新增只读辅助方法（如 `run_episodes()`）。
- 测试：在 `tests/evals/agent_short_goal_run/test_mechanical_run_scope.py` 增加用例——构造账：原样本 id 下从未有 `episode_start`，两局的 `goal_id` 分别为 `plan-r-1`、`plan-r-2`；run 粒度样本经 `mechanical_scorer` 进入判据，不是 unjudgeable；同一账对 `episode` 粒度样本仍为 unjudgeable（语义不变）。再加一个 `shop_two_npcs_interacted` 的拆分账用例。
- 核对点：registry 闸门不再直接出现 `episodes_for(sample.sample_id)`；`rules/shop.py` 同；既有 `test_replanned_success_is_included_only_for_run_samples` 仍过。
- 破坏验证：临时把 `registry.judge` 的闸门改回 `episodes_for(sample.sample_id)`，新增的拆分账用例必须失败，随后还原，生产目录 `git diff` 为空。

### CP2 显式 run_goal 与空 plan（CHANGELOG 634）

- 改动：`harness/run/run_entry.py`（D3、D4、D5，新增 `start_task_for`）；`harness/run/harness.py`（签名与 docstring）；`harness/run/begin/__init__.py`；`harness/checkpoint/restore.py:114`（`goals` 为空时用 `start_task_for(pre_run.run_id, pre_run.run_goal)`）；`evals/agent_short_goal_run/solver/runner/one.py`（D6）；`direct/trace/render.py`、`direct/trace/content.py` 仅当 `run_goals=[]` 时渲染或解析出错才改。
- 测试：
  - `tests/harness/run/` 增加：以 `goals=[]`、显式 `run_goal` 启动，假 planner 在首轮新增一条目标，run 跑完，`episode_start.goal_id` 为 `plan-<run_id>-1`，表里没有以样本 id 为 id 的条目。
  - `run_goal` 缺省且 `goals` 非空的旧路径行为不变。
  - `goals` 与 `run_goal` 都缺省时断言失败。
  - 恢复路径：`goals` 为空的存档状态经 `restore_run` 能 reset（若 `tests/harness/checkpoint/` 现有夹具不便构造，改为单测 `start_task_for` 并在汇报里说明）。
  - `one.py` 的接线：现有评测接线测试里加一条断言，传给 `harness.run` 的 `goals` 为空且 `run_goal` 来自样本。
- 核对点：`state_schema_hash()` 改动前后相同（执行方在汇报里贴两次输出）；`run_start` 账在空 `run_goals` 下渲染与解析均通过；prompt golden 未变（`tests/prompt/golden/run_plan/*` 无 diff）。
- 破坏验证：临时恢复 `begin` 的非空断言，空 plan 用例必须失败，随后还原。

### CP3 ROADMAP 占位（CHANGELOG 635，纯文档）

- 改动：`docs/ROADMAP.md`，加 E8 总览行和详述条目；`CHANGELOG.md`。
- E8 内容（执行方照此写，格式对齐 E7）：
  - 标题：run 结束后没有 run 级规划器，下一个 run goal 只能由调用方给定。
  - 状态：📋；叙事：工业；归属：项目 1；依赖：E1、E4；最后核实：2026-10-24。
  - 问题：一次 run 结束后并非任务结束，而是应重新规划下一个 run goal；现在 run goal 由调用方一次性传入（评测用样本自带 goal），run 内 plan 之上没有可规划的一层。
  - 证据：`run_entry.py` 的 `run_goal` 来源；2026-10-24 分离 run goal 与 plan 的修复（CHANGELOG 633–634）。
  - 方案：占位。run 结束后调用独立的 run 级规划器，入参为 run goal 表、各 run 的 `RunResult` 与 `run_index`，出参与 `RunPlan` 同形（新增、更新、排序），读 run 级结果、粒度比 plan 更细；run 图本身不改，由外层驱动调用，并有自己的 trace 账名；占位实现可为直通（返回调用方给定的 run goal）。
  - 验收、非目标：待定稿；非目标写“不进入 run 图内部、不改 `review_and_judge` 停机语义”。
- 不改 `AGENTS.md` / `CLAUDE.md`。

## 文件改动清单（允许范围）

- CP1：`evals/agent_short_goal_run/scorer/{utils,registry,stream}.py`、`evals/agent_short_goal_run/scorer/rules/shop.py`、`tests/evals/agent_short_goal_run/test_mechanical_run_scope.py`（及必要的同目录夹具）、`CHANGELOG.md`。
- CP2：`pokemon_agent/harness/run/{run_entry,harness}.py`、`pokemon_agent/harness/run/begin/__init__.py`、`pokemon_agent/harness/checkpoint/restore.py`、`evals/agent_short_goal_run/solver/runner/one.py`、`tests/harness/run/`、`tests/harness/checkpoint/`、`tests/evals/agent_short_goal_run/`、必要时 `pokemon_agent/direct/trace/{render,content}.py`、`CHANGELOG.md`。
- CP3：`docs/ROADMAP.md`、`CHANGELOG.md`。
- 超出范围的文件一律停下汇报。

## 验证方式

三个检查点均不调用真实模型、不跑评测、不起真实模拟器。全量 pytest（默认选项，不用 `-m` 覆盖）、`ruff check`、`ruff format --check`。

## 已知未核实

1. 空 plan 时首圈到 `plan_run` 再到 `act` 的路径，只读代码推演过，没有跑过；若 planner 首轮无新增，期望回 `review_and_judge` 并最终因规划轮数耗尽收尾。
2. 合成 `Task`（`max_steps=1`）经 MCP 世界端的 reset 是否被接受，未验证；`world_tool.py:127` 会把 Task 字段原样传出。
3. `sample.max_steps` 是否被评分器或预算接线当作期望上限使用，未全仓核实（执行方先 grep 全仓 `evals/` 与 `tests/`）。
4. `run_goals=[]` 时 `render.py:123` 之后的渲染与 `content.py` 解析未验证。
5. 其他评分器（`duration_scorer`、`movement_scorer`、`repeat_scorer`、`trace_adapter`）按 grep 不用 `goal_id`，未逐个读完。

## 停止条件

- 任何一个检查点起点不是全绿，或 HEAD 不是 fa10d49 的后继、关键哈希变化。
- 改动超出上面“允许范围”的文件。
- `state_schema_hash()` 改后与改前不同。
- 发现 `sample.max_steps` 被评分器或预算接线读取作为期望上限。
- 合成 Task 在任何真实路径上被拒绝，或 `ports.py:210` 等前置条件迫使 `max_steps` 取其他值。
- 需要修改 `run_plan` prompt、`RunState` 字段、`review_and_judge` 才能继续。
- 需要执行被禁止的 git 命令；任何真实模型调用。
- 停下后不重试、不绕过。

## 非目标

run 级规划器的实现、run goal 表与状态、目标血缘字段、prompt 调整、数据集或样本改动。
