# FM-003 连续过程被拆成过多中间task或L1目标

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：规划效率
- 状态：已观察；候选有改善线索，未证稳定
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

移动、对准、开对话、逐句推进、收尾分别建任务，增加判定、verify、摘要、重规划；遇窄预算容易只做准备步骤。

## 证据与定位

iter01商店首次拆解在同样prompt下由2个task变4个，发生于摘要生成之前；iter19拆出移动/对话及关闭/移动/交互。

## 根因与确认边界

粒度选择随模型轨迹变化，规则没有保证连续业务合并；不能把首次拆解分化归因于尚未产生的压缩摘要。

## 处理方向与取舍

decompose v5及后续、run_plan v4尝试按可验收结果合并连续过程，保留真前置/未知分支；同时修预算语义与可见性。

## 验收要点

同一业务完整完成，质量不降，task/调用/ACT和总成本减少；不通过删目标、跳证据或提高硬预算宣称优化。

## 原始记录

- [.coordination/e2e-overnight-3/THINKING_ANALYSIS.md](../../.coordination/e2e-overnight-3/THINKING_ANALYSIS.md)
- [eval_results/overnight3/iter11/ROUND_REPORT.md](../../eval_results/overnight3/iter11/ROUND_REPORT.md)
- [eval_results/overnight3/iter17/ROUND_REPORT.md](../../eval_results/overnight3/iter17/ROUND_REPORT.md)
- [eval_results/overnight3/iter19/ROUND_REPORT.md](../../eval_results/overnight3/iter19/ROUND_REPORT.md)
