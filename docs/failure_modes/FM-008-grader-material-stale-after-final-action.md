# FM-008 独立评分材料落后于最后动作或观测

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：评分证据
- 状态：历史已确认；不能声称637彻底覆盖此问题
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

机械看最后trace已完成，独立模型仍在旧画面判负。

## 证据与定位

overnight首轮009 epoch1：最后run judge在1792778818.6757结束，后续1792778946.135的sense_frame已在地图39，评分却据旧地图0判I；事件ID见原SUMMARY。

## 根因与确认边界

评分只复用最后run judge输入，预算收尾后不一定再生成新judge，保持同视野不保证覆盖最后动作。

## 处理方向与取舍

明确最终证据截止点和采样策略；不以旧judge复用冒充最终现场。637给judge最近RAM，但不自动补齐judge之后的观测。

## 验收要点

最后动作后发生切图/治疗时，评分材料时间及事件ID能覆盖事实；旧材料不会被标为最终状态。

## 原始记录

- [.coordination/e2e-overnight/SUMMARY.md](../../.coordination/e2e-overnight/SUMMARY.md)
- [docs/run-goal-split/recent-ram-evidence.md](../run-goal-split/recent-ram-evidence.md)
