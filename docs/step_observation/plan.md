# plan —— 按步观察取代事件，摘要与索引重构

> 依据：`docs/step_observation/spec.md`（v1）。

- **角色**：设计侧（我）写文档、派发、验收、提交；执行方只改代码、写测试、跑命令、按给定编号写 changelog，不提交。
- **检查点顺序**：CP1 → CP2 → CP3 → CP4，严格串行，每个检查点停下汇报，验收提交后放行下一个。
- **changelog 编号台账**：CP1 = 667，CP2 = 668，CP3 = 669，CP4 = 670；被驳回的号留空不回收。
- **分支与 worktree**：分支 `feat/step-observation`，worktree `.worktrees/step-observation`，基线 `edc18ad319ce530f986f63744aff9fb73aa9e800`；由用户在 Windows 上原生创建（`git worktree add -q`）。
- **测试口径**：已知沙箱失败 `tests/evals/test_eval_service_wiring.py::test_world_case_caller_closes_world_service_after_each_worker_outcome` 用 `--deselect`；统计用 `--junit-xml`；CP1 与 CP2 跑相关目录加 ruff，CP3 跑相关目录加 ruff，CP2 因改了提示词注册表、CP4 因删除面广，各跑一次全量。
- **回退**：一个检查点一个提交，用 `git revert`。
- **耗时**：CP1 中，CP2 大，CP3 大，CP4 中。
- **取代关系**：本任务取代 665–666 的 `dialog` 与 `memory_records` v3（旧版本文件保留，只是不再激活）。
- **合入后遗留**：读新字段的机械判据（`parcel_delivered`、`customer_hint_purchase`）在中期样本构建时另案加；渐进展开的检索 agent；文档同步；稳定性实测（`experiment/probe_settle.py`）。
