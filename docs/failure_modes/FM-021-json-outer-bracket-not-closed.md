# FM-021 JSON缺少最外层闭合括号

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：结构化输出
- 状态：摘要v4等有候选修正；不能声称彻底消除
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

长摘要或内外summary包装输出结束时少一个右大括号，解析失败。

## 证据与定位

iter13 episode摘要call 01a17043-d302-7b20-b43f-fa8286355740；iter14/full两条run摘要闭合错误。

## 根因与确认边界

原始raw可离线复现JSON语法错误，非SDK/解析器业务语义缺陷。

## 处理方向与取舍

用完整单层对象、精简重复正文、提醒最终闭合；不靠加宽解析器或硬截断输出消除报错。

## 验收要点

原始响应本身可解析；所有字段/关键证据保留，错误与重试计入用量。

## 原始记录

- [eval_results/overnight3/iter13/ROUND_REPORT.md](../../eval_results/overnight3/iter13/ROUND_REPORT.md)
- [eval_results/overnight3/iter13/ANALYSIS.json](../../eval_results/overnight3/iter13/ANALYSIS.json)
- [eval_results/overnight3/iter14/ROUND_REPORT.md](../../eval_results/overnight3/iter14/ROUND_REPORT.md)
- [eval_results/overnight3/iter14/ANALYSIS.json](../../eval_results/overnight3/iter14/ANALYSIS.json)
