# FM-029 CLI启动缺少公开API端点配置

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：启动/环境
- 状态：历史修复于启动环境；不是密钥问题
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

命令行初始化在样本执行前失败，0次有效样本。

## 证据与定位

overnight首轮005/006缺DEEPSEEK_BASE_URL，补与task.py一致的公开默认端点后才启动007/008。

## 根因与确认边界

CLI与项目正常入口对公开endpoint初始化不一致。

## 处理方向与取舍

统一入口配置或显式传公开默认端点；不打印.env或密钥值，不把启动失败计成完整基线。

## 验收要点

从干净CLI环境启动可进入样本；型号/endpoint来源明晰，敏感凭据不进JSON/输出。

## 原始记录

- [.coordination/e2e-overnight/SUMMARY.md](../../.coordination/e2e-overnight/SUMMARY.md)
