# FM-019 budget输出数值而契约要求对象

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：结构化输出
- 状态：run_plan v4候选；旧A仍可出现
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

budget写成6或10，触发TaskBudget model_type错误。

## 证据与定位

iter04首次run_plan、iter11/B和iter17/A都有实例；iter17 A预算直接为10。

## 根因与确认边界

规划意图中的数值被简写成不合法的边界数据结构。

## 处理方向与取舍

明确budget={limit:正整数,unit:本层单位}完整示例；预算建议/硬预算语义另见FM-001，不混同格式正确与预算正确。

## 验收要点

对象类型、单位、数值均合法；仍须独立验证预算策略与节点停止行为。

## 原始记录

- [.coordination/e2e-overnight-3/cache-step1-comparison/COMPARISON.md](../../.coordination/e2e-overnight-3/cache-step1-comparison/COMPARISON.md)
- [eval_results/overnight3/iter11/ROUND_REPORT.md](../../eval_results/overnight3/iter11/ROUND_REPORT.md)
- [eval_results/overnight3/iter11/ANALYSIS.json](../../eval_results/overnight3/iter11/ANALYSIS.json)
- [eval_results/overnight3/iter17/ROUND_REPORT.md](../../eval_results/overnight3/iter17/ROUND_REPORT.md)
