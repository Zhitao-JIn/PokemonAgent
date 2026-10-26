# FM-024 JSON对象中拼入无键名数组或位置值

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：结构化输出
- 状态：summarize_task v6仅三例验证；未完整全量验收
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

critical_decisions结束后直接跟数组、数字、正文，没有字段名与冒号。

## 证据与定位

iter17/full battle_item_use与shop_select_item两条，JSON错误char669/517；iter15捕捉也出现相邻无键数组。

## 根因与确认边界

对象字段输出退化为位置序列；同数组补条目时错误地另开无名数组。

## 处理方向与取舍

v6逐字段填固定对象，新增条目放原数组内部，禁止对象层逗号后直接接值。

## 验收要点

真实长短摘要都保持带键名对象；不把iter18/B三例error0宣称全量稳定修复。

## 原始记录

- [eval_results/overnight3/iter15/ROUND_REPORT.md](../../eval_results/overnight3/iter15/ROUND_REPORT.md)
- [eval_results/overnight3/iter15/ANALYSIS.json](../../eval_results/overnight3/iter15/ANALYSIS.json)
- [eval_results/overnight3/iter17/ROUND_REPORT.md](../../eval_results/overnight3/iter17/ROUND_REPORT.md)
- [eval_results/overnight3/iter17/ANALYSIS.json](../../eval_results/overnight3/iter17/ANALYSIS.json)
- [eval_results/overnight3/iter18/ROUND_REPORT.md](../../eval_results/overnight3/iter18/ROUND_REPORT.md)
