# plan —— `brain_goal_judge` 扩容

> 依据：`brain-goal-judge-intent.md` 与 `brain-goal-judge-spec.md`
> 执行约束：按 CP0→CP4 顺序；每个 CP 验收后停下，由设计侧提交该检查点变更

## 文件范围

评测数据出口与冻结版本放 `evals/dataset/brain_goal_judge/`；Inspect task 与运行逻辑放 `evals/brain_goal_judge/`；纯函数/数据测试放 `tests/`。候选审计工具只读 `eval_results/brain_choose_action/` 中两批已保存的采集产物，产物写入 `eval_results/brain_goal_judge/`。不覆盖来源记录，不访问其他 worktree，不改 `pokemon_agent/`。

## 检查点顺序

| CP | 交付物 | 验收重点 | 验收后动作 |
|---|---|---|---|
| CP0 | 只读 257 条 judge 调用盘点报告 | 输入还原、证据可判、类别覆盖分别计数；解释 67 条未匹配 | 报告并停止，等待审阅 |
| CP1 | `JudgeCase` schema、loader、旧 v1 迁移与测试 | v1 字节/语义保留；冻结引用、哈希、重复 ID 被拒绝 | 跑指定测试，停止 |
| CP2 | trace 审计/草稿生成器、逐条标签证据表、覆盖报告 | 每个标签可追溯；不能判定的显式排除；请求仍等于生产输入 | 交用户逐条审阅，停止等批准 |
| CP3 | 用户审核后的 v2 冻结物、数据清单、指标/分组 scorer | 正负样本与 hard-negative 口径；零分母；provider errors 不进分母 | 跑指定测试，停止 |
| CP4 | Inspect 接入、注册、文档同步 | task 数为 6；相关测试、全量 pytest、ruff 全绿 | 汇报完成；不跑真实模型 |

## 关键实施顺序

1. CP0 先做全量清点，不从已匹配的 190 条抽样，也不把 choose 自身的 `eligible` 当作 judge 标签。
2. CP1 先固定读取契约，再实现数据构建，避免任务逻辑继续持有数据文件格式。
3. CP2 对每个 trace 调用复原 request；优先精确重建结构化请求，并用生产 `BrainTool.judge()` 的 prompt 构造路径核 prompt 与历史图片。模型响应只用于事后对照字段，标签工具不得读取 `judge_verdict` 或 `done`。
4. CP2 的歧义与覆盖报告由用户审阅。没有审阅结论时不写入冻结 v2，也不切换 task 默认版本。
5. CP3 完成后再让 scorer 接消费 v2；CP4 最后注册和更新总目录说明，确保目录和公开 task 数一致。

## 变更记录与版本

CP 的 CHANGELOG 编号按交接分配表登记，每个检查点一个编号；执行者只改工作树，不提交。每个 CP 验收后由设计侧按项目 Conventional Commits 规范提交。v1 保持可显式读取，v2 的文件冻结后只增新版本不覆写。
