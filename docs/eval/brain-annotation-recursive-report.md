# 递归规划二十例标注与任务切换报告（v20261020_1846）

## 数据

- 原料：`brain_calls/v20261020_1846`，由十四例（`3ca4ecd`）与补采六例（`97ab011`）合并；两段 schema 哈希同为 `5d3630f2b479ee78`；`DatasetManifest.source_parts` 记录来源。562/563 只改 trace 渲染与采集控制器，未改被测行为。
- 控制账：`skipped_calls` 一条（door_transition 预算跳过），不是缺失的模型响应。
- 旧版本（v1–v4 等）字节不变，作为参考留档。

## 标注

| 家族 | 总数 | 已标注 | 排除 | 方式 |
|---|---|---|---|---|
| judge | 183 | 183 | 0 | 70 机械标签（保留来源）+ 113 请求可见证据裁定 |
| choose | 122 | 122 | 0 | 建议式；15 例机械动作集合并入可接受动作 |
| plan | 21 | 21 | 0 | 建议式；空计划合法 |
| decompose | 41 | 41 | 0 | 建议式；空更新合法 |

judge 二元标签 64 达成 / 119 未达成；决策标签 150 例（achieved 64、continue 53、blocked 33），33 例机械未达成不猜测决策类别，不进决策矩阵。

## 判定约定

- 只用请求可见的现场与同请求历史，不读采集时的模型应答。
- 对话文字被截断的现场（“Here you”“All ri”）按“尚未出现完整结果文字”；仅当前缀已能唯一确定结果（“Got away safel”“All right! PIDGEY was”）才算达成。
- blocked：同一格反复无效动作、墙/招牌挡住且历史已重复，或对话结束而目标所需菜单不会出现；未满足但仍可推进为 continue。

## 任务

四个 Inspect 任务默认版本切到 `v20261020_1846`：`brain_choose`、`brain_plan`、`brain_decompose`、`brain_judge`。plan/decompose 的结构检查已使用新请求字段（`max_push`、`max_tasks`、表快照），无需改动。

## 验证

- 假端口跑完整数据集：choose 122、judge 183、plan 21、decompose 41 样本全部成功；假评分员下 choose/plan/decompose 的质量分母等于样本数。
- `ruff check` / `ruff format --check` 通过；`tests/evals`（不含需 deepeval 的两个目录）通过。
- 未调用任何真实模型；真实模型评测另行运行。
- 环境限制：本机缺 `deepeval`（磁盘不足无法安装）、ROM 与旧 `eval_results` 目录，相关既有测试未能运行，与本次改动无关。
