# FM-004 不可变run goal被塞入可编辑plan槽位

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：目标建模
- 状态：633–635改动已处理；历史案例保留
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

planner可以放弃或替换原始总目标条目，L0任务与L1派生目标混在同一状态表。

## 证据与定位

iter04/iter07放弃sample ID条目后创建plan-...-1/-2；用户指出run goal应独立存在，plan基于它规划。

## 根因与确认边界

外部验收目标被建模为可编辑中间条目，目标身份随规划变化。

## 处理方向与取舍

run_goal独立、初始L1表可为空；planner只编辑L1，不改外部总目标。预算含义随后又被本次用户重新澄清，不能把旧预算取舍当最新要求。

## 验收要点

空plan起跑、派生/放弃L1都不改变L0目标；收尾仍按原run_goal判定。

## 原始记录

- [.coordination/e2e-overnight-3/cache-step1-comparison/COMPARISON.md](../../.coordination/e2e-overnight-3/cache-step1-comparison/COMPARISON.md)
- [eval_results/overnight3/iter07/ROUND_REPORT.md](../../eval_results/overnight3/iter07/ROUND_REPORT.md)
- [docs/run-goal-split/spec.md](../run-goal-split/spec.md)
