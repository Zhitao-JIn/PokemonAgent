# plan —— 短期样本冻结版

- 角色：设计侧写文档、验收、提交；执行方只改代码与数据、跑命令，不提交。
- 单检查点：CP1 = changelog 679（构建脚本、新数据集版本、构建逻辑测试）。
- 分支与 worktree：`feat/eval-short-frozen`、`.worktrees/eval-short-frozen`，基线 = 创建时的 `main`（含本目录文档提交）。
- 与 `feat/step-observation` 并行：本任务不碰 `pokemon_agent/`，两边文件不交集；仅 `CHANGELOG.md` 顶部会冲突，合并时按编号倒序排。
- 回退：一个提交，`git revert`。
- 后续：用新框架合并后，在 F11 的口径下跑冻结 vs 非冻结对照（另案）。
