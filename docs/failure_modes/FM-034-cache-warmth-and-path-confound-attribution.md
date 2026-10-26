# FM-034 把预热或路径差异误归因于布局

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：实验归因
- 状态：已明确限制；需重复/控制对照
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

顺序A/B总费用或命中率明显改善，便认为全由改布局带来。

## 证据与定位

iter01未改run_plan，缓存13.60%→87.17%；iter04/05总费-49.92%，但决策类别费/ACT只约-1.01%，且A有重试/目标分化。

## 根因与确认边界

缓存冷热、顺序、轨迹长度、模型随机性和并发变化混杂。

## 处理方向与取舍

报告类别未命中输入/ACT、全任务费用及路径，固定条件并重复；不拿未测script模板解释main调用收益。

## 验收要点

机制改善与整体任务收益分开表述，未变化类别和失败样本同样保留。

## 原始记录

- [eval_results/overnight3/iter01/ROUND_REPORT.md](../../eval_results/overnight3/iter01/ROUND_REPORT.md)
- [.coordination/e2e-overnight-3/cache-step1-comparison/COMPARISON.md](../../.coordination/e2e-overnight-3/cache-step1-comparison/COMPARISON.md)
- [eval_results/overnight3/iter06/ROUND_REPORT.md](../../eval_results/overnight3/iter06/ROUND_REPORT.md)
