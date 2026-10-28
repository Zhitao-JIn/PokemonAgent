# FM-051 记忆写入路径回读 trace 账

- 整理日期：2026-10-27（Europe/Berlin）
- 分类：编排执行/性能与耦合
- 状态：设计侧代码评审发现，已定修法（step-observation spec D17），尚待合入
- 适用边界：本文记录 `feat/step-observation` CP2 评审时的实现；该路径在合入前被拦下，不等于主线曾有此缺陷。

## 现象与触发

为让动作记忆的前后观察带上 RAM，`store_step_episode_memory` 每写一条动作记忆就两次调用 `trace.read_events(...)`，去 `sense_frame` 账里把 RAM 读回来。

## 证据与定位

- `pokemon_agent/harness/task/perceive/store_step_episode_memory.py` 的 `_read_ram`（已在修订中删除）。
- `pokemon_agent/trace/store.py::read_events` 的文档明确写"每次调用重扫落盘目录、不做内存缓存"；`trace/langfuse_trace.py::read_events` 读远端。
- 根因链：`sense` 取到 `ram` 却只写进账、没放进状态，写记忆的节点于是只能回读账。

## 根因与确认边界

数据本该沿状态流转，却绕道读取观测账。后果：按步调用是 O(n²)；记忆内容依赖 trace 后端是否可读，读不到就悄悄变空。性能影响是由读取方式推断的，没有实测耗时。

## 处理方向与取舍

`sense` 把 `ram` 存进状态，`close_step` 转正，记忆写入从状态取；写记忆的路径上禁止调用 `trace.read_events`，并用"读账即抛错"的 trace 替身做回归测试。

## 验收要点

`grep read_events pokemon_agent/harness/task` 无结果；替身测试在无 `sense_frame` 账时仍写出带 RAM 的前后观察；`perceive_task` 返回 `None` 时字段为空。

## 原始记录

- docs/step_observation/spec.md（D17）
- CHANGELOG 668
