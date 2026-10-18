# spec —— `brain_goal_judge`：任务完成判定评测

> 流程：intent → **spec（本文）** → plan → 执行 → 数据审阅 → 单独授权真实模型运行
> 状态：设计完成，执行待交接
> 目标：扩展现有四条示例，测生产 task judge 在真实任务历史上的目标完成判断
> 生产边界：`pokemon_agent/` 不改；本轮实现只涉及评测代码、数据、测试与评测文档

## 一、评测对象与问题

被测对象是生产 `BrainTool.judge()` 的 task 层 `done` 字段。每条样本是一条真实 task judge 调用现场：冻结 `FromHarnessToBrainToolJudgeReq`，另有独立标签 `achieved`。模型回答的 `done` 与标签比较，观察它何时把尚未完成的目标判成完成、何时漏掉已完成目标。

本评测不测 `interrupted`、`why` 的文字质量、judge 对执行动作的建议，也不测整个 run 最终是否成功。标签针对请求发生时刻；后续动作、最终 run 结果和模型自己的答案都不能反推该时刻的标签。旧 `brain_step_verify` “单步是否生效”口径不适用。

## 二、样本与真值契约

数据包归属为 `evals/dataset/brain_goal_judge/`：`schemas.py`、`loader.py` 和 `v1/`、`v2/` 冻结目录。task 装配代码仍在 `evals/brain_goal_judge/`。现有四条 v1 示例保留原样；扩容数据另建 v2，不覆盖 v1。加载默认版本改为 v2，只有 v2 达到下述冻结门槛后才切换。

`JudgeCase` 至少包含：

- `case_id`：版本内唯一 ID；
- `request`：生产 `FromHarnessToBrainToolJudgeReq` 原样冻结，含完整 task 历史及历史帧；不得把它缩成单帧，也不得把标签塞入 request；
- `achieved`：请求时刻目标是否已达成；
- `goal_family`：`navigation`、`interaction`、`party_or_inventory`、`battle_or_encounter`、`other` 之一；
- `negative_mode`：未达成样本必填且只能选一项：`near_miss`、`wrong_map_or_location`、`wrong_dialogue_or_event`、`required_state_missing`、`other`；已达成样本为空；
- `truth_method`：`mechanical` 或 `human`；机械标签必须附 `check_id`，人工标签必须有具体证据说明；
- `origin`：run/episode/task/step 与源 `judge_call` trace UUID；
- `request_sha256` 与 `evidence`：输入规范化哈希、标签依据的来源定位和摘要。

来源记录须可追到原始 trace、采集目录或冻结状态。图片应随 request 中的 `ActMemory` 一并冻结；共享图片可以按内容哈希去重，但加载后必须还原同一请求。请求还原需调用生产 prompt 构造路径作对照，确认目标、历史、知识、开关和图片均对齐；仅文本 prompt 相同不够。

标签规则按优先级执行：

1. 对应目标可由现有独立机械规则判定时，使用该规则在 judge 请求时刻的证据上计算，并记录 `check_id` 与证据定位。不得调用被测 judge 获取标签。
2. 机械规则不适用时，可由人工根据冻结的请求历史和独立世界证据标注；写明实际观察到的字段、帧或状态以及目标条件如何满足/未满足。
3. 证据缺失、冲突或目标定义含糊时标为排除，不进入冻结集；不通过模型理由、之后的动作、run 最终状态或已有 `done` 字段补标签。

一个逻辑 judge 调用最多保留一条：按 `(run, episode, task, step)` 去重；重试不算多个样本。每个 task 可有多个不同 step 的决策，但结果必须同时报告样本数、唯一 task 数与 episode 数，不将相关样本表述为独立统计样本。v2 的候选数量和类别分布由审计实测决定，不为满足预设数字放宽标签标准。

## 三、候选来源与已知限制

候选来源为 `brain_choose_action` 两批真实 task 运行记录，原批 20 个冻结起点、补采 4 个起点。已有 trace 清点为 257 次 task `judge_call`（原批 184，补采 73）；其中 190 条已验证可由 choose 请求重建出完全一致的生产 judge prompt 与图片，另 67 条尚未完成对应关系核验。上述数量是盘点依据，不是样本数或标签数。

原采集批次无法证明采集全过程代码版本不变，必须在 v2 的数据说明和运行报告中披露；补采批次有代码哈希记录。复现模型输入与证明采集版本稳定是两项不同结论。不得将 choose 数据集的 `eligible` 标记或动作标签搬用为 judge 真值。

## 四、指标与报告

每条有效响应按 `predicted = response.done` 与 `achieved` 落入 TP、FP、FN、TN。报告四格原始计数及分母，并计算：

| 指标 | 定义 | 分母 |
|---|---|---|
| 完成召回率（TPR） | TP / (TP + FN) | 已达成样本数 |
| 漏判率（FNR） | FN / (TP + FN) | 已达成样本数 |
| 完成精确率 | TP / (TP + FP) | 模型判 done 的样本数 |
| 假阳率（FPR） | FP / (FP + TN) | 未达成样本数 |
| 准确率 | (TP + TN) / N | 有效响应样本数 |

分母为 0 时显示 `NA`，同时保留 0 分母，不伪造 0%。按 `goal_family` 报四格和上述可定义的率；按 `negative_mode` 报 FP、TN、FPR 与该组分母，帮助定位难负例。多组样本来自相同 task 时同时显示唯一 task/episode 数。该数据不是独立抽样基准，不报告看似精确的总体置信区间，也不把样本微平均外推为真实游戏总体能力。

网络、密钥、provider、解析重试耗尽等错误记作 sample error，单独报告数量、类别和 ID，不计入混淆矩阵分母；不能把调用错误当成 `done=false`。正常返回的生产响应必须有布尔 `done`；若结构无效，按生产解析/重试错误路径计入 parse error，并从有效响应分母排除。v1、v2 的统计分开，不混算。

## 五、执行入口

保持 Inspect task 入口 `evals/brain_goal_judge/task.py` 与生产 `BrainTool.build(judge=...)`；数据由 `evals.dataset.brain_goal_judge.load(version)` 读取。命令沿用：

```powershell
inspect eval evals/brain_goal_judge/task.py -T version=v2
```

`version` 缺省为 v2（仅在 v2 冻结验收后变更默认值），旧 v1 可显式指定。模型名称继续取 `evals/config.json` 的 `models.judge_model`，允许 Inspect task 参数覆盖；构造和测试只用假 judge，不访问 provider。真实模型运行是单独授权，不属于这些检查点。

## 六、检查点与停止条件

### CP0：只读数据可行性审计

审计全部 257 个候选 judge 调用，逐条报告请求能否精确重建、prompt/图片是否与生产输入一致、是否具备独立真值证据、排除原因、按 truth 类别与 goal family 的分布、唯一 run/episode/task 数。重点查明 67 条未匹配记录；不把 190 条已对齐记录直接计作可标注样本。输出审计草稿到 `eval_results/brain_goal_judge/`，不改仓库冻结集。

**停止条件**：生产输入无法重建；大量候选只剩模型输出或最终结果作证；真值类别严重缺失；源 trace 与历史哈希不能闭合。遇到时先报告，不降标签标准、不启动模型。

### CP1：样本契约与读取器

新建 `evals/dataset/brain_goal_judge/schemas.py`、`loader.py`，迁移现有四条例子到 `v1/`，不改其内容；新增 loader 契约测试，核版本内文件、重复 ID、哈希和 request 类型。新增数据包出口后 task 通过该出口读数据。CP1 不注册 task、不调用模型。

### CP2：真值审阅草稿

实现候选 trace 的只读导出/核对工具与独立标签草稿生成；只自动打有明确机械规则与证据的标签，其他进入人工审阅表。报告输入对齐与标签可判性两个不同状态。将逐条草稿、证据和覆盖汇总交用户审阅；**此检查点必须停下，未获审阅不得冻结 v2**。

### CP3：冻结 v2 与评分

在逐条标签审核通过后冻结 `evals/dataset/brain_goal_judge/v2/`，计算数据清单哈希；实现四格计数及派生率、按组汇总和错误分类。用假 judge 覆盖正负判定、分母为零、组外用例、sample error 分列。保持 v1 可读且不与 v2 合并。

### CP4：接入与验收

Inspect task 默认版本切至 v2，补充回归测试；同步 `evals/registry.py`、`AGENTS.md`、`CLAUDE.md`、`docs/spec/evals/SPEC.md` 与 `docs/eval/tasks-intent.md` / `tasks-spec.md` 的 judge 条目；更新 task 数量（当前 5，注册后 6）。执行相关测试、全量 pytest、ruff check、ruff format --check。**不调用真实模型**；如需实际评分，由用户另行授权后单独运行。

任何阶段如需修改 `pokemon_agent/`、调用真实模型或更改上述真值规则，先停止并报告。

## 七、边界与验收

- 不新增/变更 production prompt、judge 逻辑、`BrainTool` 或 harness。
- 保留 v1 的四条契约样本，v2 保存扩展样本；数据与 loader 归 `evals/dataset/brain_goal_judge/`。
- 每条冻结样本可以仅从版本目录及其自包含素材重建生产请求，并独立追溯标签依据。
- 报告给出 TP/FP/FN/TN、率及分母、错误数、goal family / hard-negative 分组、task/episode 数和采集版本限制。
- 公开 task 从 5 个增为 6 个；不沿用旧 spec 的“六个变七个”。
