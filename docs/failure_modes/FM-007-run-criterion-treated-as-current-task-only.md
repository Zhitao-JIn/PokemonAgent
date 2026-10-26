# FM-007 run总目标判据被误读成只验当前task流水

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：判定/作用域
- 状态：历史证据分歧；候选口径需统一
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

前几个episode已完成部分目标，独立判定仍要求当前task包含全部目标记录。

## 证据与定位

iter03机械确认两位NPC已对话，Qwen却只认当前task一位，拒绝先前ep1/ep2材料。

## 根因与确认边界

判据沿用“本task历史”措辞，但实际样本运行层级是run；上下文作用域与文字表述不一致。

## 处理方向与取舍

区分run/episode/task验收范围，以原始证据归属为准，不让摘要自行升级成事实；先对齐范围再评价模型能力。

## 验收要点

跨局完成的run目标能累计合法证据，单task目标不越域借历史成功；同材料的判定解释一致。

## 原始记录

- [eval_results/overnight3/iter03/PROBE_REPORT.md](../../eval_results/overnight3/iter03/PROBE_REPORT.md)
- [docs/run-goal-split/spec.md](../run-goal-split/spec.md)
- [docs/run-goal-split/recent-ram-evidence.md](../run-goal-split/recent-ram-evidence.md)
