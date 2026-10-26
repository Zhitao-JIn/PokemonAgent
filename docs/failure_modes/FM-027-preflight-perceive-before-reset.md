# FM-027 起点预检在reset前读世界

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：启动/生命周期
- 状态：630已修复；历史启动失败
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

取消购买起点预检调用perceive_task时世界未初始化，worker启动失败，trace为空。

## 证据与定位

overnight2诊断叶子异常：perceive_task() before reset()；治疗共享路径当轮未运行，不能说两例都实测失败。

## 根因与确认边界

use_start_state只在本地存字节，真正服务端世界直到reset才收到；预检顺序错误。

## 处理方向与取舍

先reset再观察，验证服务端生命周期；不跳过起点验证或假造观测。

## 验收要点

新worker的取消购买/治疗预检能在reset后的真实世界上观察，失败仍保留阶段和叶子异常。

## 原始记录

- [.coordination/e2e-overnight-2/SUMMARY.md](../../.coordination/e2e-overnight-2/SUMMARY.md)
- [.coordination/e2e-overnight-3/log.md](../../.coordination/e2e-overnight-3/log.md)
