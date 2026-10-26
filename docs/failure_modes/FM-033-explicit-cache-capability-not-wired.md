# FM-033 provider支持显式缓存但配置链路未接通

- 整理日期：2026-10-25（Europe/Berlin）
- 分类：provider/缓存
- 状态：已接线；Claude iter03机制探针通过
- 适用边界：本文记录给定版本下的失败模式；历史存在不等于当前仍存在，候选或单次通过不等于稳定修复。

## 现象与触发

只移动prompt静态段，Claude却没有cache_control，无法据此宣称显式缓存已启用。

## 证据与定位

早期ClaudeProvider已有cache_marker，但_build未传；iter03原生18次请求确认3写15读，读取19335token。run摘要未完成调用，不能评价该类。

## 根因与确认边界

厂商功能只在实现类存在，未穿过settings→tool→LinkSpec→工厂。

## 处理方向与取舍

接通marker，只给支持的provider发送；按原生cache_creation/cache_read分别取证，不给自动缓存厂商塞未知参数。

## 验收要点

真实请求标记、原生usage与trace对应；跨模型混合探针只证明机制，不代表全DeepSeek收益。

## 原始记录

- [.coordination/e2e-overnight-3/CACHE_LAYOUT_PLAN.md](../../.coordination/e2e-overnight-3/CACHE_LAYOUT_PLAN.md)
- [.coordination/e2e-overnight-3/log.md](../../.coordination/e2e-overnight-3/log.md)
- [eval_results/overnight3/iter03/PROBE_REPORT.md](../../eval_results/overnight3/iter03/PROBE_REPORT.md)
