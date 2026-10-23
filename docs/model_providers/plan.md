# plan —— Claude / OpenAI provider 与选型落地

> 依据：`intent.md`、`spec.md`。分支 `feat/model-providers`，worktree `.worktrees/model-providers`，基线 main a5d7d38（含 610–613 与通宵调优）。

## 一、角色

设计侧：文档、派发、验收、提交。执行方：改代码、写测试、写 CHANGELOG、汇报，不提交。用户：授权真实调用、合入主线。

## 二、检查点顺序

CP1（620）→ CP2（621）→ CP3（622，真实探针，需授权）→ CP4（623，切换 `default.json`）。依赖：CP2 依赖 CP1 的 `_PROVIDER_PREFIXES` 改动；CP3 依赖 CP1+CP2；CP4 依赖 CP3 结果。

## 三、允许改动的文件（任务间交集核对）

- `pokemon_agent/brain/providers.py`、`tests/brain/providers/**`：与其他活跃分支无交集（待派发前 `overlap.py` 复核）。
- `pokemon_agent/settings/default.json`：CP4 才动；主仓库当前有一处未提交的 `plan.thinking` 改动，CP4 已包含，合并前用户丢弃主仓库那处。
- `CHANGELOG.md`、`AGENTS.md`、`CLAUDE.md`：共享文件，合并时按编号排序解决。
- 注意：main 的 CHANGELOG.md 第 41–81 行有已提交的冲突标记（<<<<<<< HEAD … >>>>>>> origin/main）；执行方把条目插在文件顶部（第 1 行之后的最新条目位置），不要处理这段标记，汇报时说明。

## 四、changelog 编号台账

620 CP1、621 CP2、622 CP3、623 CP4。编号 612–619 属通宵调优，不占用。

## 五、回退

一个检查点一个提交，用 `git revert`。

## 六、遗留（另案）

评分员配置、`brain_verify` 评测与双审（等 intent Q3）；`effort` 是否配置化；主仓库 CHANGELOG 冲突标记。
