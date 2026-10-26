# FM-009 判定器缺少RAM数值而误以为没有状态证据

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：观测/判定
- 状态：637接线；iter09治疗重测通过，非普遍保证
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

治疗已在RAM达到满HP，模型只看到护士台词或当前对话框，无法直接核验数值。

## 证据与定位

iter08治疗机械C：证据帧01a16f5c-188b-72a3-abd3-37d3c2cad94b队伍25/25、15/15；Qwen I称无具体HP；iter09新增RAM后C/C。

## 根因与确认边界

机械评分读取原始RAM，模型prompt却只有摘要/画面文字，证据可见性不同。

## 处理方向与取舍

run judge接入当前run/branch最近至多5次RAM，保留时间/seq/来源；独立评分沿用同一判定材料，不伪造队伍界面。

## 验收要点

数值可直接核对、伤前伤后不串对象或分支；保留旧I，不用一句收尾台词替代明确的数值判据。

## 原始记录

- [eval_results/overnight3/iter08/ROUND_REPORT.md](../../eval_results/overnight3/iter08/ROUND_REPORT.md)
- [eval_results/overnight3/iter09/ROUND_REPORT.md](../../eval_results/overnight3/iter09/ROUND_REPORT.md)
- [docs/run-goal-split/recent-ram-evidence.md](../run-goal-split/recent-ram-evidence.md)
