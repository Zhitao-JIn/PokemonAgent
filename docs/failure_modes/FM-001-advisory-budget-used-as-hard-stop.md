# FM-001 父级建议预算被执行为硬停止条件

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：预算/编排
- 状态：641已实现，离线回归通过，待真实模型验证
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

规划父级给出的task数量建议，直接成为episode的机械停止闸，尚有配置资源也不能继续。

## 证据与定位

iter19 run_plan seq9给两个NPC目标各budget.limit=1、unit=tasks；三局分别执行1/1/1个task，最后仅完成1位NPC。episode判停使用step >= goal.max_steps。

## 根因与确认边界

641前的实现把父级模型budget.limit映射到goal.max_steps并硬执行。用户2026-10-25已明确：父级仅给建议预算，硬预算由配置给；该设计已于641实现，真实模型效果尚未复测。

## 处理方向与取舍

后续分开建议预算与配置硬预算。建议影响规划策略，不能单独触发机械预算耗尽；配置硬闸继续保护动作、task、局数、时长等资源。641已落地，两层建议1/99的真实图离线回归通过。

## 验收要点

父级建议1个task、配置允许更多时，可按需要执行多个task；仅触及相应配置硬上限才机械判停。资源单位与停止原因可追溯。

## 原始记录

- [eval_results/overnight3/iter19/ROUND_REPORT.md](../../eval_results/overnight3/iter19/ROUND_REPORT.md)
- [eval_results/overnight3/iter19/ANALYSIS.json](../../eval_results/overnight3/iter19/ANALYSIS.json)
- [docs/budget/run-budget-spec.md](../budget/run-budget-spec.md)
- [docs/run-goal-split/spec.md](../run-goal-split/spec.md)

## 641修复追踪

[预算语义与验证](../budget/ADVISORY_AND_HARD_LIMITS.md)；[真实图回归](../../tests/budget/test_advisory_budget.py)。旧iter19失败证据保留，不以离线通过冒充付费实测成功。
