# FM-038 缺货币charge或未落盘用量被误作零成本

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：计费/指标
- 状态：持续统计限制；不是已确认无费用
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

cost scorer为N，或中断只保留部分usage，容易把N/缺失当0。

## 证据与定位

overnight2记录¥4.033302仅已落盘部分；本轮cost普遍N，另按cached_tokens与真实时段独立计价，未知超时费用一直另列。

## 根因与确认边界

原scorer缺完整货币账，模型usage/账户扣款/在途账不等价。

## 处理方向与取舍

N保持不可用；缓存输入属于输入、reasoning属于输出，按每次时段/型号真实价格算，Qwen等不混入DeepSeek预算。

## 验收要点

已知/未知分列、预算留余量；中断/评分未刷新不伪造完整总账。

## 原始记录

- [.coordination/e2e-overnight-2/SUMMARY.md](../../.coordination/e2e-overnight-2/SUMMARY.md)
- [eval_results/overnight3/iter01/ROUND_REPORT.md](../../eval_results/overnight3/iter01/ROUND_REPORT.md)
- [eval_results/overnight3/iter18/ROUND_REPORT.md](../../eval_results/overnight3/iter18/ROUND_REPORT.md)
- [eval_results/overnight3/iter19/ROUND_REPORT.md](../../eval_results/overnight3/iter19/ROUND_REPORT.md)
