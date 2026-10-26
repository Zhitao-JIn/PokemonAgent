# FM-031 思考消耗额度却没有可解析正文

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：provider/重试
- 状态：已有EmptyCompletion与纯文本降级；本探针未复现
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

模型输出reasoning但正文为空，不能当作成功JSON，也不能静默丢用量。

## 证据与定位

现有provider的EmptyCompletion异常携带completion/reasoning用量；这不自动保证跨层trace和报告完整落盘，须逐层核对。638回归覆盖plan空正文后纯文本重试关闭thinking。

## 根因与确认边界

正文与思考预算/模型模式有厂商差异，简单缩max_tokens可能更容易截断或无正文。

## 处理方向与取舍

保留显式异常、有限重试和真实开关记录；不把max_tokens当成通用独立thinking预算。

## 验收要点

空正文时可见错误与用量，重试开关/实际请求一致；文本与图像差异须分别验证。

## 原始记录

- [docs/spec/build/NODE_THINKING.md](../spec/build/NODE_THINKING.md)
- [.coordination/e2e-overnight-3/log.md](../../.coordination/e2e-overnight-3/log.md)
