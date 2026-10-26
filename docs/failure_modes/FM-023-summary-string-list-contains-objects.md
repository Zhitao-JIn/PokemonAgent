# FM-023 摘要字符串数组中出现对象项

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：结构化输出
- 状态：summarize_task v5候选
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

critical_decisions等列表输出step/decision对象，JSON合法但schema不合法。

## 证据与定位

iter15/full购买样本critical_decisions为对象数组，真实EpisodeSummary复现string_type。

## 根因与确认边界

模型将更丰富叙述结构替换契约规定的list[str]。

## 处理方向与取舍

显式每项必须字符串，给全字段示例；不把解析器改成任意对象列表来掩盖漂移。

## 验收要点

所有约定列表元素类型一致，正文证据不因扁平化丢失。

## 原始记录

- [eval_results/overnight3/iter15/ROUND_REPORT.md](../../eval_results/overnight3/iter15/ROUND_REPORT.md)
- [eval_results/overnight3/iter15/ANALYSIS.json](../../eval_results/overnight3/iter15/ANALYSIS.json)
