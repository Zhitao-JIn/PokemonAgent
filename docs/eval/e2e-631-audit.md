# 631：端到端调优审计报告

2026-10-24；工作区e2e-tune3，起点dd1078b，开跑前按用户要求快进main至fa10d49。完成iter00与iter01各20例；没有更新任何模型权重。

## 实验与验收口径

- 两轮四条被测链路均deepseek-flash，text/judge thinking=false，plan/verify thinking=true；独立评分qwen3.8-flash、thinking=false。
- iter00使用合入main的活动模板；iter01仅summarize_task v2→v3，新增紧凑输出约束，其他活动模板及12个知识文件hash一致。两轮均串行。
- 用户授权修复捕捉机械评分后，对iter01八项机械/数值scorer离线重评，冻结Qwen评分直接复用；没有真实模型调用、重跑游戏或额外费用。
- 本提交包含报告及支持该结论的评分器修复/回归；未验收的摘要候选与本机模型配置保留在工作区，不随本提交合入。

## 结果

| 指标 | iter00 | iter01（离线校正） |
| --- | ---: | ---: |
| task_scorer / 机械通过 | 19/20 | 20/20 |
| 红线 | 1 | 0 |
| result_grade | 20/20 | 20/20 |
| cost scorer | 20个N | 20个N |
| ACT | 62 | 73 |
| 模型调用 | 352 | 404 |
| duration，样本耗时之和（秒） | 2348.968 | 2697.120 |
| movement | 可测9/20，合计0 | 可测10/20，合计0 |
| overshoot | 可测19/20，合计15 | 可测20/20，合计14 |
| repeat，样本均值 | 1.166667% | 0.954545% |
| 已记录DeepSeek费用（元） | 1.56902704 | 1.57710334 |
| 元/ACT | 0.02530689 | 0.02160416 |
| 缓存输入占比 | 49.73% | 58.72% |

movement=N来自脚本内部路径不可测，不能把可测值0解释为没有移动。cost=N来自trace没有显式货币账；上表价格按实际调用时间及cached_tokens独立核算。repeat取样本均值，不相加百分比。

## 捕捉评分修复的证据

原规则只接受同帧all right!.*was caught；实际分页依次是All right! PIDGEY was与PIDGEY was caught!。后一句已有完整结果，仍被旧规则拒绝，run判成后又派生R3。修复接受完整was caught!，不接受仅RED used POKé BALL!或不完整前半句。

- iter01完整结果帧：01a16d3a-d1fd-77fe-91bd-82c3f5984c2f，随后两帧仍重复完整结果。
- 机械I→C，R3移除，overshoot N→0；依赖成功归类的数值metadata及Inspect聚合重新计算。Qwen评分、所有模型usage及原始日志哈希保持一致。
- iter00只采到All right! PIDGEY was；同一修复规则离线核对仍fail，不能追溯套用iter01完整证据。两轮通过差异不是已证明的摘要压缩收益。

## 效率与因果结论

task摘要输出42,592→27,458（-35.53%）、该环节费用下降22.33%；但总调用增加14.77%、耗时增加14.82%、动作增加17.74%、整轮费用增加0.51%。元/ACT下降14.63%同时分母扩大，不能单凭比值判提效。暂不接受摘要压缩为整体效率收益。

thinking总量67,176→86,280。首个有效摘要之后24,459→49,997，但最大峰值仍持有关键切图事实；相同初始prompt也出现任务拆分差异。详见[根因分析](e2e-631-root-cause-analysis.md)，现有证据不能确认摘要信息减少是原因。

## 费用与历史可比性

本次已记录DeepSeek累计¥3.14613038；按北京时间周末非高峰（缓存命中0.02、未命中1、输出4元/百万token），reasoning属于输出，不重复收费。iter01有一次decompose超时，服务端可能已计费但本地缺usage，故该数字是已记录费用，不是账户账单精确总额。上轮已记录约¥4.033302不计本次。

DeepSeek输入/输出：iter00为1,596,262/187,685，iter01为1,843,812/198,564；Qwen输入/输出：104,354/1,757及91,799/1,694，不计入DeepSeek预算。Haiku调用0。

旧轮缓存整体40.9%、plan0%、summarize_run0%、summarize_task7.8%；本次iter00依次49.73%、13.60%、7.47%、23.28%。旧轮不完整且配置不同，仅作描述性比较。iter01未改run_plan却升至87.17%，缓存预热不可忽略。

## 原始产物与复核

完整trace、.eval、20行九scorer表、差异、版本及知识清单SHA-256位于本机eval_results/overnight3/iter00与iter01；它们是忽略的大型实验产物，不在本次提交中。原始iter01.eval与trace未修改；旧派生报告在iter01/original_reports，校正日志在iter01/rescored/corrected.eval，来源在rescored/provenance.json。

- 原始iter01日志SHA-256：`fe8fcb2f89c830439cfecb132d99e5d531b34d730e0bc9194281229b4539b071`。
- 修复规则SHA-256：`c04a4474d74fb7f48cc6cfc46da7ccba7143c5c716a6fd22fea268a8e7383ed2`。
- summarize_task v3 hash：`3b1357fc56992020df707111b422b6705cb69b9eacfff6856ba83094e4a299ca`（仅实验候选，不随本提交）。
- pytest tests/evals/agent_short_goal_run/test_battle_results.py tests/evals/agent_short_goal_run/test_evals_checks.py：68项通过；新增6个回归用例。
- 新模板泛化lint：60条样本文本、0命中；活动注册表22项校验通过。评分修复文件ruff check及format --check通过。

本阶段按用户要求停在iter01之后，自动跟进已暂停；下一轮须用户单独启动，方向为缓存布局，最多5例并发。
