# 建议式参考与四个 Inspect 脑能力任务

2026-10-20 按用户口径调整：失败 choose 可以通过合理纠偏继续评估；多个动作可同样合理。
plan/decompose 的拆分只是建议，后续由 Inspect AI 的独立评分模型评估候选质量。

| 任务 | 默认版本 | 有评分参考 / 原料 |
|---|---|---:|
| choose | v4 | 206 / 207 |
| plan | v3 | 26 / 26 |
| decompose | v3 | 36 / 37 |
| judge | v4，沿用原标注 | 289 / 289 |

总计557/559。choose 比上一版恢复75条，不重采、不改写原始请求或旧标注。
此前判断“无从保证哪一键必成功”的43条不再因此排除，允许有限探索并按合理性给分；
32条错误子目标现场允许纠正站位、对象或任务前提。

所有建议都基于该调用自己的输入。choose 只看到本次task目标时，不把别的L1原目标的禁止条款
导入该输入；当前请求明确的限制仍优先。场景名称、来源路径、建议叙述不能当成现场事实。
门口当前未传送并不证明已经尝试过某个动作，建议中不补造未出现的失败历史。

参考含逐例上下文、建议动作和建议路线，但不构成穷尽答案白名单。候选没有列在建议中，
不能仅据此扣分；合法且有依据的替代、纠偏或探索同样可以高分。choose 仍是一键一决策，
“多种可接受答案”不改变生产Action契约。正常场景也不强制唯一按键或脚本。

choose/plan/decompose 的 AI 质量维度为：现场与范围、推进或恢复、边界与历史。
各维度0..1评分，等权平均；明确保留部分分数。任一维度无法判定或评分缺项/重复/数字无效，
整例质量分不进分母。Inspect 同时展示 quality_mean 与 quality_count，0分照常计入分母。
能力掩码、单步、预算与合法索引等结构检查另列。judge 按既有真假标注统计准确率，保留原证据。

保留的2条排除项：

- choose：RUN光标已经满足目标，现有能力没有stop；继续生成任何动作都不能表达上层应当结算。
- decompose：已逃跑但原目标禁止重新遇敌，且产物必须包含至少一个任务；现有输入无法表达合法补救。

对应plan冲突现场可以通过 why/note 和 abandoned 更新说明阻塞，因此纳入质量评分。
其是否仍能派发的结构诊断分与说明是否合理的语义分分别展示。

```powershell
inspect eval evals/brain_choose/task.py -T version=v4
inspect eval evals/brain_plan/task.py -T version=v3
inspect eval evals/brain_decompose/task.py -T version=v3
inspect eval evals/brain_judge/task.py -T version=v4
```

choose/plan/decompose 可用 `-T model=...` 和 `-T grader_model=...` 分别指定被测和评分模型；
`grader_model=none` 只产生结构检查，不伪造语义评分。`python -m evals.brain_choose -T ...`
同样进入Inspect。旧choose集合命中工具保留为未登记的legacy诊断，不再作为公开任务入口。

本次验证使用Fake Chooser/Fake Grader，没有启动真实模型跑分；AI评分本身也不是机械真值或人审。
全量回归1761 passed、7 skipped、3 deselected；新增12项测试包含未列入建议的候选可正常获得AI质量分。
