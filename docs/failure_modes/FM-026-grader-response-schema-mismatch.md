# FM-026 独立评分员输出字段与评分schema不匹配

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：评分格式
- 状态：630增加有限格式纠正；历史N保留
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

评分员返回decision，而要求achieved/reason，最终N。

## 证据与定位

overnight2 wild_encounter、battle_fight_menu各有N；不是任务机械失败证据。

## 根因与确认边界

模型跟随被评分材料中的判定格式，而非独立评分响应契约；解析重试处理不足。

## 处理方向与取舍

评分格式纠正有限重试，保留每次原文和耗尽原因；不把N自动改成I/C。

## 验收要点

合法schema正常评分；持续非法输出明确不可判并停止相应不安全推进，不原样无限烧额度。

## 原始记录

- [.coordination/e2e-overnight-2/SUMMARY.md](../../.coordination/e2e-overnight-2/SUMMARY.md)
- [.coordination/e2e-overnight-3/log.md](../../.coordination/e2e-overnight-3/log.md)
