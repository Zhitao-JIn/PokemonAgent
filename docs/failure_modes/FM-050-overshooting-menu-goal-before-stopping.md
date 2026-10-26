# FM-050 目标只到中间菜单却继续操作到成交状态

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：历史验收/过冲
- 状态：历史二级证据；近期仍需看overshoot
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

目标要求停在某菜单/确认层，执行继续到买成功台词，最终状态已偏离要求。

## 证据与定位

bootstrap经验列“终帧其实是买成功的台词”作为历史误判回归；近期overshoot也单独记录，不自动等于该旧案例复现。

## 根因与确认边界

业务完整完成不一定等于当前任务目标，阶段边界被“继续做完业务”的策略覆盖。

## 处理方向与取舍

以原目标层级停，不因通用合并任务规则越过中间态验收；购买/不购买等约束保留。

## 验收要点

要求确认界面时停在确认且未成交；要求购买时才进一步核对交易完成证据。

## 原始记录

- [docs/experiences/2026-09-01-eval-framework-bootstrap.md](../experiences/2026-09-01-eval-framework-bootstrap.md)
- [eval_results/overnight3/iter15/ROUND_REPORT.md](../../eval_results/overnight3/iter15/ROUND_REPORT.md)
