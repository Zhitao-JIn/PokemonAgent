# P0 探测记录 —— checkpointer：嵌套子图的定位、读回、写入与续跑

> 对应 `docs/checkpoint/plan.md` P0 ｜ 2026-09-26 ｜ 只读探测，仓库代码未改
> 环境：设备侧临时 venv（Python 3.12.14，langgraph 1.2.11、langgraph-checkpoint 4.2.0、langgraph-checkpoint-sqlite 3.1.1、pydantic 2.13.5），`tests/` 231 条全部通过作为基线。
> 探针：用 `tests/_fake_run.py` 的假大脑 / 假世界跑真实三张图，run 图挂 `SqliteSaver`；主线跑一个 2 局 × 2 task 的 run，
> 在 `begin_task` 里取执行上下文；再在新 thread 上从第 1 局第 2 个 task 恢复。探针脚本是一次性的，不进仓库。

## 结论一览

| # | 核实项 | 结论 |
|---|---|---|
| K1 | `begin_task` 里能否从 `checkpoint_map` 推出 `episode_ref` | **通过**（4/4 个 task） |
| K2 | 存档时怎么核 `episode_ref` 指的是"episode 图进 `act` 前" | **通过**，但要换判据（见下） |
| K3 | 按 `episode_ref` 读回的 `EpisodeRunState` 是否等于 episode `act` 的入参 | **通过** |
| K4 | 在 run 的 `act` 里对 episode 图 `update_state(as_node="plan_episode")` | **通过** |
| K5 | `invoke(None)` 是否从 `act` 续跑、外层是否照常往下走 | **通过** |

spec §九第 5 条（新线账序）依赖 Q4 的存档位置，挪到 Q5 验收。

## K1 `episode_ref` 的推导

`begin_task` 里 `get_config()["configurable"]`：

- `checkpoint_ns` 形如 `act:<run 的 act 这次执行的 id>|act:<episode 的 act 这次执行的 id>`；
- `checkpoint_map` 恰好两条：`""` → run 图进 `act` 前那一条；`act:<id1>` → episode 图进 `act` 前那一条。

`checkpoint_ns` 按 `|` 去掉最后一段，就是 `checkpoint_map` 里 episode 图那一条的键。4 个 task 全部如此。

## K2 存档时的核对：不用 `get_state`，改看父指针

- 在图外对 episode 图 `get_state(episode_ref)` 报 `ValueError: No checkpointer set`——episode 图编译时没带 saver。即使带上，按源码也会因为嵌套命名空间被转派给名为 `act` 的子图而报错（`pregel/main.py:1405-1416`）。
- 往 config 里塞 LangGraph 内部键 `__pregel_checkpointer` 后能拿到 `next == ("act",)`，但那是私有常量，不用。
- **公开 API 的判据**：`saver.get_tuple(episode_ref).metadata["parents"][""] == run_ref.checkpoint_id`——episode 图这条 checkpoint 的父指针就是 run 图进 `act` 前那一条。4/4 成立。
  它说明这条 checkpoint 属于这一次 run 的 `act`；"下一格是 `act`"由位置保证（`begin_task` 只在 episode 的 `act` 里被调用），并在恢复时写入后再核一次（K4）。

## K3 读回

`saver.get_tuple(episode_ref).checkpoint["channel_values"]` 缺 `memory`、`output` 两个字段——从没被写过的 channel 不落盘。
按 `EpisodeRunState.model_fields` 取有的字段、缺的取模型缺省值，校验成模型后与 episode `act` 当时的入参 `model_dump()` 逐字段相等。

## K4 写入

新 thread `r1@b-probe` 上：run 图 `update_state(as_node="plan_run")` 后 `next == ("act",)`；run 的 `act` 里：

- `episode_graph.update_state(get_config(), 读回的状态, as_node="plan_episode")` 成功，写进本次 `act` 的命名空间 `act:<新 id>`（与父线的命名空间不同）；
- `episode_graph.get_state(get_config()).next == ("act",)`——节点内的 config 带着父图的 checkpointer，不会被转派；
- `update_state` 的**返回值**只有 `thread_id` / `checkpoint_ns` / `checkpoint_id`，不带 checkpointer，拿它 `get_state` 会报 `No checkpointer set`。核对要用 `get_config()`。

## K5 续跑

`episode_graph.invoke(None, {"recursion_limit": …}, context=…)` 之后 episode 图的节点顺序：

```
act → perceive → review_and_judge → plan_episode → act → perceive → review_and_judge
```

第一个执行的是 `act`，`perceive` / `plan_episode` 没有在它之前重跑；episode 图跑完，run 的 `act` 拿到 `EpisodeOutput`（`episode_id` 正确），run 图回到 `perceive` 并照常派下一局。

## 对 spec 的影响

1. §四第 4 步：task 级存档核 `episode_ref` 改用父指针判据（K2），`Checkpointer` 不需要持有 `episode_graph`。
2. §五第 4 步：读回时缺席的 channel 取模型缺省值（K3）。
3. §五 `resume_episode`：写入后的核对用 `get_config()`，不用 `update_state` 的返回值（K4）。
