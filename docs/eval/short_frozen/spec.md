# spec —— 短期样本冻结版（20 条，冻结 plan·L1）

> 版本 v1。依据：`docs/eval/short_frozen/intent.md`（待确认）、`docs/eval_freeze/`（冻结机制，已合入 `main`：662–664）。
> 数据来源：`docs/eval/short_frozen/tasks.json`（设计侧写好的 20 条 task 表，执行方照抄，不自行改写措辞）。
> 本任务：changelog **679**，分支 `feat/eval-short-frozen`，worktree `.worktrees/eval-short-frozen`，基线 = 创建时的 `main`。

## 一、决定表

| 编号 | 决定 |
|---|---|
| D1 | 新数据集版本目录 `evals/agent_short_goal_run/dataset/v20261028_short_frozen/`（沿用日期前缀规则）。父版本 `v20261021_retest5` **不改**，作为"task 表由 decomposer 自由拆"的对照；冻结版与它形成 A/B，不另存对照副本 |
| D2 | 构建方式：新增确定性构建脚本 `evals/agent_short_goal_run/dataset/build/short_frozen.py`，读父版本 `samples.jsonl` 与同目录下的 `short_frozen_tasks.json`（从 `docs/eval/short_frozen/tasks.json` 原样复制过来，字节一致），写出新版本目录；目标目录已存在则报错，不覆盖；脚本可重复运行得到逐字相同的输出 |
| D3 | 每个样本的变化**只有**三处：`dataset_version` 改为新版本名；`tier` 设为 `"short"`；`goals` 设为恰一条 `SampleGoal`（`goal`、`success_criteria`、`max_steps` 取自 `tasks.json` 的 `episode`，`tasks` 取自同条的 `tasks`）。其余字段（`start`（含 `source_sha256`）、`goal`、`success_criteria`、`max_steps`、`check_id`、`rubric`、`red_lines`、`k_metric`、`split`、`initial_state_hint`、`behavior`、`category`、`granularity`）**逐字不变**，包括字段顺序以外的任何值 |
| D4 | `states/`：从父版本整目录复制 22 个 `.state` 文件，每个文件的 sha256 与父版本一致（脚本复制后逐个校验，不一致即报错）；`rubric.json`、`coverage.md` 原样复制；新写 `revision.json`：`parent_version`=`v20261021_retest5`，`change` 写明"冻结 plan·L1：每条样本新增 tier=short 与一张固定 task 表，其余字段与父版本一致"，`task_counts`（每个样本的 task 数）、`source_files`（`tasks.json` 的 sha256） |
| D5 | 加载校验：新版本经 `loader.load(version)` 必须得到 20 条，`validate_tiers` 通过（short 档：`goals` 恰一条且 `tasks` 非空）；`loader.check(version)` 通过（起点状态文件存在且 sha 一致）。**这是构建步骤的核对，不写成对数据集内容的常驻测试**（评测测试只验平台，不审数据集内容，2026-10-21 原则）。起点预检若有需要模拟器的脚本（`build/preconditions.py` 一类），按它的现有用法跑一次并把结果写进汇报；跑不了就写明原因，不要自行替代 |
| D6 | 常驻测试只测**构建逻辑**，用合成的父版本样本（2–3 条，含一条会被拆成两个 task 的）：构建出的每个样本只变 D3 的三处；目标目录已存在时报错；`tasks.json` 缺某个样本或多出未知样本时报错；`goals[0].max_steps == len(tasks)`；构建结果经 `validate_tiers`；用 `solver/runner/one.py` 的 `run_arguments` 与 `loop_overrides` 对 short 档样本得到期望的目标表、`frozen_tasks`（键为目标条目的 `task_id`）与两个冻结开关全开。测试文件 `tests/evals/agent_short_goal_run/test_short_frozen_builder.py` |
| D7 | 不新增样本、不改判据与红线、不改现有版本目录、不冻结 plan·L2（choose）、不改生产代码（`pokemon_agent/` 零改动） |
| D8 | 三个"待确认"的取舍已定：版本目录名见 D1；单步样本的 task 表只有一条，作用是排除 decomposer 把一个动作拆成多个 task；只有 `knowledge_shop_interaction` 拆成两个 task（每个 task 一位不同顾客），其余 19 条各一个 task，合计 21 个 task |

## 二、允许改动文件

- `evals/agent_short_goal_run/dataset/build/short_frozen.py`（新）、`evals/agent_short_goal_run/dataset/build/short_frozen_tasks.json`（新，从 `docs/eval/short_frozen/tasks.json` 复制）
- `evals/agent_short_goal_run/dataset/v20261028_short_frozen/`（新目录，由脚本生成后一并纳入）
- `evals/agent_short_goal_run/dataset/loader.py`（仅当版本需要登记才改，改前先核实 `loader` 是否有登记表；没有就不改）
- `tests/evals/agent_short_goal_run/test_short_frozen_builder.py`（新）
- `CHANGELOG.md`（顶部新增 679 条目，格式照抄上方条目）
- 超出这个清单就停下汇报；`docs/` 不许改。

## 三、验收

1. 新版本目录存在，含 `samples.jsonl`（20 行）、`rubric.json`、`coverage.md`、`revision.json`、`states/`（22 个文件）。
2. 对每个样本，与父版本逐字段比较：除 `dataset_version`、`tier`、`goals` 外全部相同；贴出比较脚本的输出摘要（20 条全部通过）。
3. `states/` 每个文件 sha256 与父版本一致；`revision.json` 里 `source_files` 的 sha256 与 `build/short_frozen_tasks.json`、`docs/eval/short_frozen/tasks.json` 都一致（后两者字节相同）。
4. `loader.load` 得到 20 条，`validate_tiers`、`loader.check` 通过（贴输出）；`run_arguments(sample)` 对 `knowledge_shop_interaction` 得到 2 个 task、其余各 1 个（贴一条示例输出）。
5. 脚本重复运行（先删目标目录）得到的 `samples.jsonl` sha256 不变（证明确定性）。
6. ruff format、ruff check、ruff format --check 全绿；全量 pytest（带 `--deselect tests/evals/test_eval_service_wiring.py::test_world_case_caller_closes_world_service_after_each_worker_outcome`，统计读 junit，读完删临时文件）failures=0、errors=0；`skipped` 与基线相同（起点先跑一次取基线）；两种 `git diff --stat` 逐行一致。

## 四、停止条件

起点不是全绿（除已知沙箱失败外）；`loader` 要求登记而登记方式看不懂；父版本样本与 `tasks.json` 的样本集合不一致；需要改 `pokemon_agent/` 下代码或 `docs/`；需要调用真实模型或启动模拟器（预检脚本若必须启动模拟器，先在汇报里说明再做，不要擅自）；需要执行被禁止的 git 命令。

## 五、非目标

不运行真实评测；不做中期样本（那是另一条线：`docs/eval/mid_tasks/`）；不做对照实验本身。
