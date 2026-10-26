# FM-039 混合版本或未完成批次被当完整基线

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：实验完整性
- 状态：已标明限制；历史结果原样保留
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

不同核心代码、模型、RAM范围或n=1结果被平均成统一重复基线。

## 证据与定位

iter08只完成r1三例；iter09最新索引商店/菜单用旧v4无RAM、治疗用637/v5；iter07候选B根本未执行。

## 根因与确认边界

完成状态、证据范围和重复次数没有作为比较前提。

## 处理方向与取舍

保留全部attempt、缺失/失败状态和配置hash，逐样本匹配，不拿旧20例均值比较新单例或宣称候选退步。

## 验收要点

均值/范围附n与条件；新代码/观测输入变化后重建基线，未完成对照不作因果结论。

## 原始记录

- [eval_results/overnight3/iter07/ROUND_REPORT.md](../../eval_results/overnight3/iter07/ROUND_REPORT.md)
- [eval_results/overnight3/iter08/ROUND_REPORT.md](../../eval_results/overnight3/iter08/ROUND_REPORT.md)
- [eval_results/overnight3/iter09/ROUND_REPORT.md](../../eval_results/overnight3/iter09/ROUND_REPORT.md)
- [eval_results/overnight3/iter18/ROUND_REPORT.md](../../eval_results/overnight3/iter18/ROUND_REPORT.md)
