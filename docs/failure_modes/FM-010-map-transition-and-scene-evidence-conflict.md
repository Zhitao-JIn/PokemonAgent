# FM-010 切图事实与scene或当前帧规则冲突导致继续执行

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：判定/证据解释
- 状态：已观察；根因混合，未证单一prompt解释
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

已看到map_id变化，仍因scene为空或要求indoor而追加室内移动/对话。

## 证据与定位

iter01门口最大decompose reasoning=10242；输入保留0→39与goal_done，上一judge却以scene为空、缺indoor继续。早期007也有见切图仍否认变化的记录。

## 根因与确认边界

状态型/变化型验收、字段缺失与跨帧证据被混用；不是已确认摘要删除关键切图事实。

## 处理方向与取舍

明确判据类型和证据来源，缺失字段不擅自补真，也不把真实跨帧变化抹掉；先查判据本身是否要求scene。

## 验收要点

用真实前后帧同时覆盖应过/不应过案例；不能把任意切图替换明确indoor验收。

## 原始记录

- [.coordination/e2e-overnight-3/THINKING_ANALYSIS.md](../../.coordination/e2e-overnight-3/THINKING_ANALYSIS.md)
- [.coordination/e2e-overnight/SUMMARY.md](../../.coordination/e2e-overnight/SUMMARY.md)
- [.coordination/e2e-overnight-2/SUMMARY.md](../../.coordination/e2e-overnight-2/SUMMARY.md)
