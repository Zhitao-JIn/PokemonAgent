# FM-006 RunStream未先按run_id过滤导致证据串run

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：trace/评分
- 状态：636已修复；历史缺陷
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

共享trace目录下，查询不存在或不同run也可能读到同一批事件；别的run恢复事件还会污染分支选择。

## 证据与定位

CHANGELOG636审计记录：不存在run ID仍读回276条事件并能判通过。

## 根因与确认边界

local读口忽略run_id，且若先选branch再筛run会留下顺序错误。

## 处理方向与取舍

先按run_id过滤，再识别/选择branch；langfuse额外过滤保持同一语义。

## 验收要点

共目录多run、不同恢复分支和不存在ID均隔离；不存在run不能借别的执行证据通过。

## 原始记录

- [CHANGELOG.md（636）](../../CHANGELOG.md)
- [docs/run-goal-split/spec.md](../run-goal-split/spec.md)
- [.coordination/e2e-overnight-3/log.md](../../.coordination/e2e-overnight-3/log.md)
