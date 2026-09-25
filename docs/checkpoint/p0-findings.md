# P0 核实记录 —— checkpointer

> 对应 `docs/checkpoint/plan.md` P0 ｜ 2026-09-25 ｜ 只读核实，仓库代码未改
> 环境：设备侧临时 venv（Python 3.12，langgraph 1.2.11、langgraph-checkpoint-sqlite 3.1.1），`tests/` 全部通过作为基线。
> 探针：用 `tests/_fake_run.py` 的假大脑 / 假世界跑真实三张图，run 图挂 `SqliteSaver`、`durability="sync"`、`thread_id="r1@main"`；
> 在两个 `act` 节点入口处取 saver 快照并与节点入参比对。探针脚本是一次性的，不进仓库。

## 结论一览

| # | 核实项 | 结论 |
|---|---|---|
| K-a | 两个 dispatch 在"进 `act` 前"状态上重算是否一致 | **通过** |
| K-b | 续跑跳过 `begin_*` 是否会漏掉副作用 | **通过** |
| K-c | 帧槽是否需要入档 | **不需要**（不迁进 `TaskState`） |
| K-d | 真实状态模型经 sqlite 往返 | **能往返，但 allowlist 必须逐个类名登记**——spec §5.4 要改写法 |
| K-e | 存档库增量 | **比预想大**：假跑一局约 3.4 MB / 92 个 checkpoint，真机会更大，需要对策 |

## K-a 纯函数重算（通过）

run 层 2 次 `act`、episode 层 4 次 `act`，每次都成立：

- saver 里外层"最新一条"的值 == 该 `act` 节点收到的 `state`（run 层逐字段；episode 层 13–14 个通道全等）；
- `run.act.dispatch(state)` 连算两次结果相同，且与 `act` 实际返回的 `goals` / `episode_input` / `step` 相等；
- episode `act` 步骤 1 的复刻（即将提出的 `dispatch_task`）连算两次相同，`tasks` 与 `act` 返回相等，`task_input` 与实际传给 `run_task` 的相等。

依据：两段逻辑只读 `state`（`current_knowledge(state)` 也只读 `state.ep_ctx`），没有时间、随机或外部 IO。

## K-b 开局入口的副作用（通过）

静态核对三个入口，副作用只有"记一条开局账 + 装初始状态"：

| 入口 | 副作用 |
|---|---|
| `run_entry.new_run` | `game.reset`（世界起点）+ 构造 `RunState`；`run_start` 在图内 `begin` 格记 |
| `episode_entry.begin_episode` | 记 `episode_start` + 构造 `EpisodeRunState` |
| `task_entry.begin_task` | 记 `task_start` + 构造 `TaskState` |

探针跑出 `episode_start` 2 / `episode_end` 2、`task_start` 4 / `task_end` 4，与入口调用次数一致。
续跑跳过 `begin_*` 时，开局账已在父分支（存档点在它之后），拼接血缘后恰好一条，不重复、不缺。
run 级恢复从 `begin` 格重跑、会记新的 `run_start`——这是新分支自己的开局，符合预期。

## K-c 帧槽（不需要入档）

`task/frames.py` + `task/perceive/sense.py` + `store_step_episode_memory.py` 静态核对：

1. task 的第一圈 `perceive`：`sense` 先把本 task 开局帧写进槽；`store_step_episode_memory` 因 `state.action is None` **直接返回、不读槽**；
2. 第二圈起读的是 `before.step` 与 `before.step + 1` 两帧，二者都是本 task 内由 `sense` 写入的。

所以 task begin 时槽里有什么都不会被读到；恢复时槽为空，读到的结果与原线一致。**P3 不迁帧槽。**

## K-d sqlite 往返（能往返；allowlist 写法要改）

- 默认序列化器下：状态能往返，`EpisodeRunState.model_validate` 后字段类型正确（`goal` 是 `Task`、`tasks[0]` 是 `TaskEntry`），
  但每个自定义类型都会告警"反序列化了未登记类型，将来版本会拦截"——本次共 19 条。
- 按包前缀登记 `allowed_msgpack_modules=[("pokemon_agent",)]` **无效**：每个类型都被拦截，报错要求逐个写成 `(模块路径, 类名)`，
  如 `('pokemon_agent.brain.interface.domain.goal', 'Goal')`、`('pokemon_agent.schemas.harness.domain.entry_status', 'EntryStatus')`。
- **对策（写进 P3）**：装配 saver 时从 `RunState` / `EpisodeRunState` / `TaskState` 出发，沿字段类型递归收集全部 Pydantic 模型与枚举，
  生成精确的 `(模块, 类名)` 列表。状态模型一改，列表自动跟着变，无需手工维护；spec §5.4 那句"登记状态模块"改为此写法。

## K-e 存档库增量（比预想大，需要对策）

- 假跑一个 run（2 局、4 个 task、每 task 数键）：**92 个 checkpoint，sqlite（含 WAL）约 3.4 MB，平均约 37 KB / 个**。
  LangGraph 每个 super-step 都存一份各通道的完整值，状态里的列表（任务表、结算、上下文）每步整份重复。
- 真机状态更大（观测、检索回来的记忆与知识全文都在状态里），单局键数也多得多，按比例估算单 run 可能到数十至上百 MB。
- 帧槽不入档（K-c），这部分不再增加。
- **对策候选（P3 实测真机一局后定）**：
  1. 每个 run 一个 sqlite 文件（`checkpoints/<run_id>/langgraph.sqlite`），整 run 删除即清理，不影响其他 run；
  2. 清理时只保留被清单引用的 checkpoint（存档点"进 `act` 前"那几条），其余 super-step 的 checkpoint 可删；
  3. 两者可叠加。建议先做 1（改动最小），P3 量完真机再决定要不要 2。

## 对 spec / plan 的改动

- spec §5.4：allowlist 改为"从三种状态模型递归生成 `(模块, 类名)` 列表"；saver 文件位置待 P3 量完真机后在 1 / 2 中定。
- plan P3：删去"视 K-c 迁帧槽"；加"生成 allowlist"与"真机量库增量"两项。
