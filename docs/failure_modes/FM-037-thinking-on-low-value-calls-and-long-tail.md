# FM-037 事实整理和局部校验出现高额thinking长尾

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：thinking成本
- 状态：638节点开关已接线；质量收益仍待验证
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

verify、规划或摘要单次思考很长，缓存改善无法降低这部分输出费。

## 证据与定位

iter17 thinking92845，verify33.44%、decompose22.79%、plan21.75%；单次plan8722、verify7247。iter19关闭verify和三摘要均0thinking，但任务未完成。

## 根因与确认边界

原四链路把verify与三摘要、plan与decompose绑定，无法独立测需不需要思考；高thinking并不自动说明信息缺失。

## 处理方向与取舍

按11逻辑节点开关、逐provider取证；优先实验事实整理与verify。不得把关闭成功当正确率已验证，或只看thinking占比不看绝对量。

## 验收要点

请求开关、usage、质量与总费用一起核对；thinking含于输出，不重复计数。

## 原始记录

- [.coordination/e2e-overnight-3/THINKING_COST_REVIEW.md](../../.coordination/e2e-overnight-3/THINKING_COST_REVIEW.md)
- [.coordination/e2e-overnight-3/RUN_THINKING_DISTRIBUTION.md](../../.coordination/e2e-overnight-3/RUN_THINKING_DISTRIBUTION.md)
- [docs/spec/build/NODE_THINKING.md](../spec/build/NODE_THINKING.md)
- [eval_results/overnight3/iter19/ROUND_REPORT.md](../../eval_results/overnight3/iter19/ROUND_REPORT.md)
