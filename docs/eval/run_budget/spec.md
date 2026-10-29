# spec —— 706：评测的运行预算接线（中期与长期样本按样本定预算）

> 编号 706。直接动 `evals/` 下的评测入口配置与 solver；每个任务一个 worktree；执行方不提交；删除由用户做。
> 依据：`docs/plan/2026-10-29-schedule.md` 第六节、`docs/eval/changes_20261028.md` 第四节最后一行。

## 一、事实（设计侧核对）

- 样本的 `max_steps` 在 `evals/agent_short_goal_run/solver/runner/one.py` 里**只用于启动校验的引导任务**（`_task_for`）与冻结目标条目的 `Task.max_steps`；**不是 run 的预算**。
- run 的硬预算来自 `evals/config.json` 的 `budget`：`max_total_actions: 60`、`wall_clock_s: 600`、`max_episodes: 3`，经 `eval_overlay` 写进每次运行的配置，对所有样本一视同仁；另有顶层 `timeout: 600`（每个样本的进程时限）。
- 后果：短期样本够用；中期（oracle 56 到 104 个决策，样本预算 190 到 330）与长期（oracle 238 步，预算 720）会被 60 个动作与 600 秒截断。683、689 的 spec 里写的"样本预算"因此没有生效。

## 二、决定

| 编号 | 决定 |
|---|---|
| D1 | 短期（`tier="short"`）**保持现状**：用配置里的 `budget` 与 `timeout`，一个字节的行为都不变 |
| D2 | 中期与长期：`max_total_actions = sample.max_steps`（数据集是预算的真源）；`wall_clock_s = ceil(max_steps × seconds_per_action) + reserve_s`；进程 `timeout = wall_clock_s + timeout_margin_s`；`max_episodes`：中期取该样本目标表的条数（冻结的目标表条数就是 episode 数，判负即收尾），长期取配置项 `long_max_episodes` |
| D3 | 新配置项放 `evals/config.json` 顶层的一个新节 `budget_derivation`：`seconds_per_action`（默认 40，依据 `docs/eval/e2e-631-audit.md` 里每动作约 38 秒）、`reserve_s`（默认 120）、`timeout_margin_s`（默认 300）、`long_max_episodes`（默认 6）。缺这一节时按上面默认值，且**不改变短期行为** |
| D4 | 预算推导做成一个纯函数（输入样本与配置，输出三个数加 `max_episodes`），放在评测代码里（例如 `evals/common/overlay.py` 旁或 `evals/agent_short_goal_run/solver/` 下一个小模块），`sample_overlay`（每个样本的覆盖配置）调用它；**不改 `pokemon_agent/`** 里预算的语义与读取方式 |
| D5 | 进程 `timeout` 是每个样本的时限：先读 `task.py` 与 solver 里 `timeout` 现在怎么被强制（可能是任务级的 `time_limit` 或 solver 里的计时），把它改成**按样本**生效（中期与长期用 D2 的值，短期仍用配置的 `timeout`）；若 inspect 的时限只能任务级，则在 solver 里用样本级的计时上下文实现，先说明你的做法 |
| D6 | 有效预算必须**可审计**：写进每次运行的配置快照（`write_run_config` 产物）与 `run.json`，并在 `baseline_context.json` 里记 `budget_derivation` 与逐样本的有效预算表 |
| D7 | 测试全部合成：推导函数对三种档位的正反例（短期不变；中期的 `max_steps` 与目标表条数；长期的 `long_max_episodes`；缺 `budget_derivation` 节时的默认值；`seconds_per_action` 非正时报错）；`sample_overlay` 对同一份配置在短期与中期样本上得到不同预算；**真实核对**只做一次：对 `v20261028_short_frozen`、`v20261028_mid`、`v20261028_long` 三个数据集的全部样本打印"样本、档位、有效 `max_total_actions`、`wall_clock_s`、`timeout`、`max_episodes`"一张表，贴进汇报 |
| D8 | 允许范围：`evals/config.json`（只加 `budget_derivation` 一节）、`evals/runconfig.py`（键声明与默认值）、`evals/common/overlay.py`、`evals/agent_short_goal_run/{task.py,solver/**}`、新增小模块与测试、`CHANGELOG.md`。不改 `pokemon_agent/`、`docs/`、数据集、评分规则 |
| D9 | 验收：先取全量基线（预期 `tests=2986` 左右，以实测为准；`failures=0`、`errors=0`、`skipped=72`）；最终同口径；守卫四条 `[ OK ]`；ruff 三项；两种 `git diff --stat` 逐行一致；`CHANGELOG.md` 顶部新增 706 条目；现有数据集的 `load` 与 `check` 条数不变（20、20、5、1） |

## 三、不做

不改短期的预算与超时；不改 `pokemon_agent/` 里预算的读取与停止语义；不做每动作时间的自适应估计（常数配置即可）；不接入费用护栏（那是 696，690 单独用）。
