# 二十场景全脑调用采集

完成 20/20；模型尝试 737；双向对账缺失 0。

Harness 终止类型：{'budget_exhausted': 1, 'goal_done': 17, 'stalled': 1, 'actions_exhausted': 1}。goal_done 是运行时结论，不代替独立机械真值。

| 类别 | 完整输入 | 分层数量 | 独立标签 | 待审 rubric |
|---|---:|---|---:|---:|
| judge | 289 | {'episode': 60, 'run': 23, 'task': 206} | 206 | 83 |
| plan | 26 | {'run': 26} | 0 | 26 |
| decompose | 37 | {'episode': 37} | 0 | 37 |
| choose | 207 | {'task': 207} | 21 | 186 |
| summary | 99 | {'episode': 19, 'run': 20, 'task': 60} | 0 | 99 |

完整请求未抽样、未去重；错误和业务失败保留。summary 含 task、episode、run。
所有旧响应仅作 baseline 审计，未用于生成参考答案。独立标签子集可用已有运行器；其余 rubric 仍需独立评分或审阅，不计入二元/动作命中率分母。

baseline_scores.json 保留原始机械诊断与独立标签下的 baseline 分数。
旧机械规则存在已知数量框漏判：商品列表解码未变时，也可能已在原屏幕弹出数量框。
数量确认独立标签以原屏幕为准；旧规则失败不直接等同真实未完成。
投球例的 Aww! It appeared to be caught! 也是结算结果；旧规则只列部分话语，可能漏判。

## 等待与耗时

Port 耗时包含模型等待、重试、退避和解析；具体尝试起止见 sources.zip。

| Port | 调用数 | 总耗时秒 | 中位数秒 | P95 秒 |
|---|---:|---:|---:|---:|
| episode/decompose | 37 | 61.43 | 1.62 | 2.09 |
| episode/judge | 60 | 83.47 | 1.27 | 2.16 |
| episode/summarize | 19 | 88.08 | 4.06 | 6.09 |
| episode/verify | 19 | 28.31 | 1.41 | 1.83 |
| run/judge | 23 | 29.45 | 1.25 | 1.55 |
| run/plan | 26 | 36.08 | 1.23 | 1.89 |
| run/summarize_run | 20 | 99.78 | 4.96 | 6.28 |
| task/choose | 207 | 229.40 | 1.06 | 1.59 |
| task/judge | 206 | 261.14 | 1.23 | 1.66 |
| task/reflect | 206 | 0.22 | 0.00 | 0.01 |
| task/summarize_task | 60 | 248.64 | 3.85 | 5.88 |
| task/verify | 60 | 89.69 | 1.29 | 2.34 |

## 范围与限制

L0：本 run 全部 episode；背景其他 run。L1：本局全部 task；背景同 run、同 goal_id 的其他 episode。L2：本 task 全部 act；背景本局同目标文本的此前 task。
每例从独立空 memory 恢复，所以跨 run 背景为空；这批数据不能证明长程记忆收益。
budget_skipped 原账单列，不制造未发生的模型调用。来源包保留所有九方法的实际录制与 trace；五族导出不包含 verify/reflect 评分任务。
二十个起点不是独立留出测试集。重复现场、模型生成的差目标和预算耗尽均反映采集分布，不能当作整套能力的泛化结论。
