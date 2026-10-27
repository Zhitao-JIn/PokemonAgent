# plan —— 评测时冻结规划层

> 依据：`docs/eval_freeze/spec.md`（v1）。

- **角色**：设计侧（我）写文档、派发、验收、提交；执行方只改代码、写测试、跑命令、按给定编号写 changelog，不提交。
- **检查点顺序**：CP1 → CP2 → CP3，严格串行，每个检查点停下汇报，验收提交后放行下一个。CP2 依赖 CP1 的配置字段；CP3 依赖 CP1、CP2 的接口。
- **changelog 编号台账**：CP1 = 662，CP2 = 663，CP3 = 664；被驳回的号留空不回收。
- **分支与 worktree**：分支 `feat/eval-freeze`，worktree `.worktrees/eval-freeze`，基线 `e7155c3d922f28e92289e3deacf4f4fb02ad6582`；由用户在 Windows 上原生创建。
- **回退**：一个检查点一个提交，用 `git revert`。
- **与别的任务的文件交集**：派发前跑 `python .coordination/overlap.py`；本任务的允许文件见 spec 第三节。
- **耗时**：CP1 小，CP2 中，CP3 小到中。
- **合入后遗留**：文档同步（AGENTS.md、CLAUDE.md、`docs/ROADMAP.md`）；中期 / 短期样本本身的构建（见 `docs/eval/mid_tasks/intent.md`）；脚本内对话文字不进账的问题（另案）。
