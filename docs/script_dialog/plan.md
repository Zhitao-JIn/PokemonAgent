# plan —— 脚本内对话文字进账

> 依据：`docs/script_dialog/spec.md`（v1）。

- **角色**：设计侧（我）写文档、派发、验收、提交；执行方只改代码、写测试、跑命令、按给定编号写 changelog，不提交。
- **检查点顺序**：CP1 → CP2，严格串行，每个检查点停下汇报，验收提交后放行下一个。
- **changelog 编号台账**：CP1 = 665，CP2 = 666；被驳回的号留空不回收。
- **分支与 worktree**：分支 `feat/script-dialog`，worktree `.worktrees/script-dialog`，基线 `e7155c3d922f28e92289e3deacf4f4fb02ad6582`；由用户在 Windows 上原生创建。
- **与冻结任务（`feat/eval-freeze`，662–664）的关系**：文件不交集，可并行；合入顺序不限。
- **回退**：一个检查点一个提交，用 `git revert`。
- **耗时**：CP1 中，CP2 小。
- **合入后遗留**：读新字段的机械判据（`parcel_delivered`、`customer_hint_purchase`）在中期样本构建时另案加；文档同步另案。
