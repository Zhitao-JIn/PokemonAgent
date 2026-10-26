# FM-018 success_criteria输出数组而契约要求字符串

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：结构化输出
- 状态：decompose v6候选；后续未稳定复现该类型
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

分解结果多次ParseFailure，纠正重试才成功，增加thinking和输出。

## 证据与定位

iter10/B三例分别1/2/2次，共5条error，new_items[0].success_criteria为数组。

## 根因与确认边界

实际字段类型错误已确认；“只列证据”措辞是否诱导列数组只是prompt解释假设。

## 处理方向与取舍

v6给完整通用对象和字符串类型，多个条件分号连接；不放宽Pydantic类型吞掉错误。

## 验收要点

真实输出符合字符串契约，重试和失败计费保留；离线示例合法不等于LLM稳定合法。

## 原始记录

- [eval_results/overnight3/iter10/ROUND_REPORT.md](../../eval_results/overnight3/iter10/ROUND_REPORT.md)
- [eval_results/overnight3/iter11/ROUND_REPORT.md](../../eval_results/overnight3/iter11/ROUND_REPORT.md)
