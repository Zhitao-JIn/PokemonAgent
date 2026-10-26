# FM-025 摘要额外套type/content包装

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：结构化输出
- 状态：旧A仍发生；候选约束待持续验证
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

返回{"type":"json_object","content":{...}}，内部字段正确但外层不符合消费契约。

## 证据与定位

iter18/A NPC摘要JSON合法，仍summary_parse_error；失败原文见ANALYSIS.json。

## 根因与确认边界

把请求的JSON输出模式描述当作需要返回的业务包装层。

## 处理方向与取舍

明确只返回约定摘要对象，不额外包装；不要混同解析器已支持的summary包装与任意type/content包装。

## 验收要点

正文和字段位于消费方需要的位置，真实输出无需剥未知包装也可验证。

## 原始记录

- [eval_results/overnight3/iter18/ROUND_REPORT.md](../../eval_results/overnight3/iter18/ROUND_REPORT.md)
- [eval_results/overnight3/iter18/ANALYSIS.json](../../eval_results/overnight3/iter18/ANALYSIS.json)
