# FM-040 把错误优先优化擅自收紧为零错误硬门槛

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：执行流程
- 状态：用户已纠正；旧控制器逻辑仍待修订
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

质量20/20通过但有可恢复错误，被拒绝标验收；旧脚本还会据此回退/阻断全量。

## 证据与定位

iter14/full 20/20、6错误；iter17/full 20/20、2错误。用户明确指出没有要求0错误，只要求错误较多时优先优化。

## 根因与确认边界

执行者把诊断指标升级为未经要求的硬验收条件。旧OVERNIGHT_ERRORS与driver仍保留这段历史，不代表当前授权。

## 处理方向与取舍

撤回额外零错误门槛，保留错误数、类型、重试成本及质量结论。重启循环前先改实验计划/控制器，不能直接复用旧门槛。

## 验收要点

质量通过与错误负担分别报告；可恢复错误不自动否决任务；资金守卫与真实持续接口故障仍独立保护。

## 原始记录

- [.coordination/e2e-overnight-3/efficiency-loop/OVERNIGHT_ERRORS.md](../../.coordination/e2e-overnight-3/efficiency-loop/OVERNIGHT_ERRORS.md)
- [eval_results/overnight3/iter14/ROUND_REPORT.md](../../eval_results/overnight3/iter14/ROUND_REPORT.md)
- [eval_results/overnight3/iter17/ROUND_REPORT.md](../../eval_results/overnight3/iter17/ROUND_REPORT.md)
- [.coordination/e2e-overnight-3/CONTINUATION.md](../../.coordination/e2e-overnight-3/CONTINUATION.md)
