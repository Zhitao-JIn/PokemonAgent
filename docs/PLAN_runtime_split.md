# PLAN —— harness 依赖注入面拆分：`HarnessDeps` → `RunRuntime` + `EpisodeRuntime`

> 状态：**已落地**（CHANGELOG 2026-09-22 第 180 条）。本文档留设计依据与字段归属账。

## 一、要解决的问题

`HarnessDeps` 是个混装袋：run 级与 episode 级的依赖住同一个对象，两级节点**都能看见**
对方的依赖——episode 图的 21 个节点在结构上看得见 `planner` 和两个行为开关（0914 起
只是"不读"），run 侧也看得见帧槽。隔离只存在于纪律里，不存在于类型里。

## 二、两个设计决定

**① 粒度：一次 run 一份（甲），episode runtime 由 `build.py` 同时装配。**
（乙 = 每局新建）的唯一动机是"帧槽跨局残留"，但 `remember_frame` 自带跨局整对清空，
甲粒度下不成立。甲让装配仍然只发生在 `build.py` 一处（铁律 3）；乙要求 run 期新建，
得往 run 侧塞工厂，凭空多一条装配路径。若将来真要 run 内多局并发，迁移面很小：
构造点从 `build.py` 挪进 `run/nodes/episode.py`，字段不变——但先决问题是
**每局要自己的模拟器实例**（本机 Event 41 红线，见 `~/.workbuddy` 长期记忆）。

**② 嵌套持有：`RunRuntime.episode: EpisodeRuntime`。**
接线上的硬约束：episode 图的 `context=…` 由 `episode_entry._invoke` 显式传（形态 B），
episode 自己拿不到第二份 context，只能由 run 侧递下去。`run/nodes/episode.py`
那一格做 `episode_entry.run_new(runtime.context.episode, …)`。
附带收益：`game` / `brain_tool` 只存在一份（在 EpisodeRuntime 上），
`new_run` 的世界起点载入写 `run_rt.episode.game.reset(...)`（穿透，不复制字段）。

## 三、字段归属（全仓读者统计核实）

| 字段 | RunRuntime | EpisodeRuntime | 说明 |
|---|---|---|---|
| `trace` / `memory` / `reviewer` | ✓ | ✓ | **同一实例**，装配时复制引用 |
| `run_id` | ✓ | ✓（复制） | 不可变；`new_run` 里**双侧同步写** |
| `planner` | ✓ | ✗ | 只有 run 侧 `plan` 读；episode 节点结构上看不见 |
| `game` / `brain_tool` | ✗ | ✓ | episode 独占 |
| `frame_before` / `frame_after` | ✗ | ✓ | episode 独占；`remember_frame` 兜跨局清空 |
| `episode` | ✓（嵌套） | — | 必传字段 |

共享项隔离的是**类型可见性**，不是运行期实例——`run_rt.trace is run_rt.episode.trace` 恒真。

## 四、官方用法核对（langgraph 1.2.11 实测）

- `CompiledStateGraph.invoke` 参数表里有具名 `context`（默认 `None`）——一等参数。
- `Runtime` docstring："Convenience class that bundles **run-scoped context** …
  **injected into graph nodes and middleware**"。
- `context_schema` + `Runtime[...]` 是 1.x 官方 DI 通道（`config["configurable"]` 的继任者）。
- **F10 仍在**：形态 B 里子图的 `context_schema` 声明不被校验——两个 runtime 的声明是
  给人和脚本看的契约；漏改签名的症状 = 运行期 `AttributeError` 炸在第一个读字段的节点上。

## 五、验证闸门

1. grep 双清零：`HarnessDeps` 与 `harness.deps` 在代码里归零（docstring 里只留"已删"说明）；
2. `ruff check` 全绿；`compileall` 干净；
3. `pytest tests` 全绿（5 个测试文件的构造类型同步改）；
4. 下次真机 run 顺带核一眼：装配两 runtime + `run_id` 双侧同步 + reset 穿透。
