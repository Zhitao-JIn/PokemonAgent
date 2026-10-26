# FM-022 JSON字符串内引用原文未转义

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：结构化输出
- 状态：verify v5候选；后续单轮未复现不代表保证
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

why等字段直接嵌入未转义双引号，破坏JSON。

## 证据与定位

iter14/full verify失败raw中的原文引用可复现语法错误。

## 根因与确认边界

自由文本引用被直接插入JSON字符串，未执行合法转义。

## 处理方向与取舍

通用规则要求中文引号或合法JSON转义，理由保留最小充分依据；不能删负样本或索引来凑短。

## 验收要点

含双引号、换行与特殊字符的真实回答仍可解析且语义完整。

## 原始记录

- [eval_results/overnight3/iter14/ROUND_REPORT.md](../../eval_results/overnight3/iter14/ROUND_REPORT.md)
- [eval_results/overnight3/iter14/ANALYSIS.json](../../eval_results/overnight3/iter14/ANALYSIS.json)
