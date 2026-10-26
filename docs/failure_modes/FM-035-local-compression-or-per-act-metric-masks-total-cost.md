# FM-035 局部压缩或每ACT降价掩盖全任务变贵

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：效率评估
- 状态：多轮已出现；不接受单指标选优
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

摘要短了、缓存高了或每ACT便宜了，但执行次数和总耗费增加。

## 证据与定位

iter01 task摘要输出-35.53%，ACT62→73、调用352→404；iter06每ACT费用降8.91%，总费用升66.99%；iter16缓存62.25%但总token+37.58%。

## 根因与确认边界

局部指标与全任务目标不同，分母ACT本身可被无效动作放大。

## 处理方向与取舍

先守任务/红线/result，再看每任务总token、费用、调用和时长，归一化指标仅作诊断。

## 验收要点

不能靠增加ACT压低元/ACT；报告正反变化，不丢掉劣化指标。

## 原始记录

- [eval_results/overnight3/iter01/ROUND_REPORT.md](../../eval_results/overnight3/iter01/ROUND_REPORT.md)
- [eval_results/overnight3/iter06/ROUND_REPORT.md](../../eval_results/overnight3/iter06/ROUND_REPORT.md)
- [eval_results/overnight3/iter16/ROUND_REPORT.md](../../eval_results/overnight3/iter16/ROUND_REPORT.md)
