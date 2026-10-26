# FM-028 ExceptionGroup只记录外层字符串掩盖启动根因

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：错误可观测性
- 状态：630展开异常；历史记录缺口保留
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

Inspect看到泛化异常组，无法分清世界、模型、评分阶段；失败样本没有启动trace。

## 证据与定位

overnight2实际root是世界未reset，但worker先只str(ExceptionGroup)，延迟刷新时后续worker已启动。

## 根因与确认边界

异常包装丢失嵌套叶子列表和失败阶段，错误信息无法指导停止与定位。

## 处理方向与取舍

展开叶子异常并记录阶段；启动前尚无事件也要明确“无trace”而非视为无错误。

## 验收要点

多层异常组能定位具体异常类/原因/阶段，不泄露密钥；错误被发现后不继续盲目跑。

## 原始记录

- [.coordination/e2e-overnight-2/SUMMARY.md](../../.coordination/e2e-overnight-2/SUMMARY.md)
- [.coordination/e2e-overnight-3/log.md](../../.coordination/e2e-overnight-3/log.md)
