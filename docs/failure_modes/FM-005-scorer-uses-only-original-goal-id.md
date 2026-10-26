# FM-005 run级评分只按原goal ID找局导致不可判

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：评分范围
- 状态：633修复已落地；旧N不改写
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

实际完成多个派生目标，机械评分却报“账本里没有派给这个目标的局”。

## 证据与定位

iter04/iter07新goal_id不等于sample ID，episodes_for(sample_id)为空，机械N、独立Qwen C。

## 根因与确认边界

run验收错误复用了按单目标ID精确匹配的局切片。N是无法核对，不等于机械I。

## 处理方向与取舍

run级在当前执行线上收集全部相关episode；episode/task仍保持各自作用域，不伪造目标血缘或重评全部旧数据。

## 验收要点

原目标ID没有episode但当前run有合法派生局时，能执行原run判据；其他run与分支的局不混入。

## 原始记录

- [.coordination/e2e-overnight-3/cache-step1-comparison/COMPARISON.md](../../.coordination/e2e-overnight-3/cache-step1-comparison/COMPARISON.md)
- [eval_results/overnight3/iter07/ROUND_REPORT.md](../../eval_results/overnight3/iter07/ROUND_REPORT.md)
- [docs/run-goal-split/spec.md](../run-goal-split/spec.md)
