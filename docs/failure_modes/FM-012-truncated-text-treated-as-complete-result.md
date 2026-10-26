# FM-012 用截断前缀或常识补齐完成结果

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：判定假阳
- 状态：候选judge v7/捕捉知识；新全量单次通过
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

run仅看到“All ri”就认定捕捉完成，独立和机械均不接受。

## 证据与定位

iter15/full catch_throw_ball I/I、R3；iter17/full本例C/C但不足以证明稳定修复。

## 根因与确认边界

将动作成功、状态变化或熟悉台词前缀当成目标明确要求的完整文字。

## 处理方向与取舍

judge v7按文本判据核对关键完整成分；领域台词/动画分页留在知识，不能用摘要或常识补未见文字。

## 验收要点

截断/动画未结束负例拒绝，真实完整分页结果可通过；不要因此扩大纯数值判据要求。

## 原始记录

- [eval_results/overnight3/iter15/ROUND_REPORT.md](../../eval_results/overnight3/iter15/ROUND_REPORT.md)
- [eval_results/overnight3/iter15/ANALYSIS.json](../../eval_results/overnight3/iter15/ANALYSIS.json)
- [eval_results/overnight3/iter17/ROUND_REPORT.md](../../eval_results/overnight3/iter17/ROUND_REPORT.md)
