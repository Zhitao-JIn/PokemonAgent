# run goal 与可编辑目标表分离 —— plan

依据：`docs/run-goal-split/intent.md`、`docs/run-goal-split/spec.md`（v1）。基线：主线 fa10d49。

## 角色

- 设计侧：写文档、派发、验收、提交（执行方不提交）。
- 执行方：在 `.worktrees/run-goal-split`（分支 `fix/run-goal-split`）改代码、写测试、写 CHANGELOG 条目、汇报。
- 用户：建 worktree、提交 docs、合入主线。

## 检查点顺序与依赖

| 检查点 | 内容 | CHANGELOG 编号 | 依赖 |
|---|---|---|---|
| CP1 | 评分按 run 取局 | 633 | 无 |
| CP2 | 显式 run_goal、空 plan、reset 来源 | 634 | CP1 已验收并提交 |
| CP3 | ROADMAP E8 占位 | 635 | CP2 已验收并提交 |

CP1 可单独合入，不依赖 CP2；CP2 之前，评测入口仍带种子条目，CP1 的口径在两种形态下都成立。

## 每个检查点我的核对点

- CP1：`registry.py` 与 `rules/shop.py` 不再直接调 `episodes_for(sample.sample_id)`；新增“原 id 从未有局”的账用例，run 粒度进判据、episode 粒度仍 unjudgeable；破坏验证（还原闸门使新用例失败）已做。
- CP2：`state_schema_hash()` 前后一致；空 plan 用例走到 `plan_run` → `act`；旧路径（`run_goal` 缺省且 `goals` 非空）行为不变；`one.py` 接线断言；`run_start` 空 `run_goals` 渲染与解析；prompt golden 无 diff；已知未核实第 1–4 条有结论。
- CP3：只改 `docs/ROADMAP.md` 与 `CHANGELOG.md`，E8 行与详述条目格式对齐 E7。
- 每个检查点：`git diff --stat` 无行尾整体翻转；CHANGELOG 数字是亲眼见到的实数；全量 pytest、`ruff check`、`ruff format --check` 全绿。

## 任务允许改动的文件清单

见 spec“文件改动清单（允许范围）”。与其他活跃分支的交集（2026-10-24 `overlap.py`）：`tune/e2e-overnight-3` 改了 `evals/agent_short_goal_run/scorer/rules/catch.py` 与 `CHANGELOG.md`；本任务不碰 `catch.py`，`CHANGELOG.md` 为共享文件（顶部插入，按编号保留两边）。`docs/audit-r1` 只与 CHANGELOG 共享。

## changelog 编号台账

| 号 | 用途 | 状态 |
|---|---|---|
| 633 | CP1 | 已派发 |
| 634 | CP2 | 预留 |
| 635 | CP3 | 预留 |

注意：分支 `tune/e2e-overnight-3` 的 CHANGELOG 顶号是 632，本分支从 633 起。

## 回退方式

一个检查点一个提交，回退用 `git revert`，不重写历史。CP1 与 CP2 可分别回退。

## 耗时

CP1 约半小时；CP2 约 1–2 小时（含多处测试夹具）；CP3 十分钟。

## 合入

分支完成后由用户合入主线。合入前我核对分支相对 fa10d49 的提交范围，以及此后主线是否动了同一批文件；`CHANGELOG.md` 顶部插入处冲突按编号保留两边。同步主线用 merge，不用 rebase。

## 合入后遗留

- run 级规划器（ROADMAP E8）：实现、run goal 表与状态、跨 run 持久化。
- 样本步数上限改由 planner 预算兜底后，评测单样本成本分布需观察一轮再决定是否要给 planner 加样本级预算提示。
- 其他评分器（duration、movement、repeat、trace_adapter）是否隐含目标 id 假设，CP1 不覆盖，另案核对。
- 独立 Qwen 评分员对拆分后的 run 给 C 的原因未核实（`result_grade.py` 的输入是否带原始 run goal），另案。
