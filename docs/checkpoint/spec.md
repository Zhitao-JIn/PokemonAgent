# spec —— checkpointer（v2：两级存档 + 回放到 task）

> 流程位置：intent.md → **spec.md** → plan.md → PR → production
> 状态：**已定稿（09-25 v2）**，含 intent C10–C18 → 下一步重写 `docs/checkpoint/plan.md`
> 依据：`docs/checkpoint/intent.md`（09-25 修订）｜ v1（三级 begin 存档 + 图外续跑）已实现为 CHANGELOG 229–236，原文存档在 `spec-v1.md`
> 为什么改：v1 恢复 episode / task 级存档时，被打断的那一局要在图外跑完、再替外层 `act` 交差，
> 这一段存不了档（v1 的 L1），补它要让续跑图单独挂 saver、另开 thread。v2 换个思路：**存档只放在不嵌套的位置，
> task 靠回放 trace 到达**，恢复全程都在图里正常跑。

---

## 一、已定前提（09-25 讨论）

| # | 决定 |
|---|---|
| D1 | **完整存档只有两级**：run 级 begin（保留）、episode 级 = run 的 `act` 一开始（`dispatch` 之前）。两处都是 run 图"进 `act` 前"或进图前，不嵌在任何 `act` 里 |
| D2 | **task 不存完整档**，只在每个 task begin 存一份**世界快照**（`world.state`），供回放到达时直接读档，不重演模拟器（有随机事件，不靠重演） |
| D3 | 恢复沿用原 `run_id`，新 `branch`（`b<n>`）；trace `meta.branch`、分支登记表、血缘读法沿用 v1 |
| D4 | 记忆整根快照只在两级完整存档时拍；**回放段的记忆读按 trace 里的 `refs` 直接取**，不重跑检索（避免检索的不确定性） |
| D5 | **回放只依赖 trace + 存档**，不依赖随机数、墙钟或"同样输入应得同样输出"；trace 字段不够就补 trace（§六） |
| D6 | **回放段不写 trace**；新线从第 k 个 task 开局起记账，分叉点 = 父线里这个 task 的 `task_start` 的前一条 |
| D7 | 回放段每一笔本该落的账都与父线逐条比对，对不上即"回放分叉"，恢复中止 |
| D8 | 每局结束时把本局的账封存进它的 episode 存档（C14），回放优先读存档自带的账 |
| D9 | 记忆查询的筛选与排序都放进查询条件，harness 不二次加工；所有记忆读都记读账（C17、C18） |

## 二、存档点

| 存档 | 位置 | 存什么 |
|---|---|---|
| run 级 | `run_entry.new_run`：`game.reset` 之后、进 run 图之前（同 v1） | 世界 + 记忆 zip + `RunState` 原件 |
| episode 级 | run 的 `act` 节点第一件事（`dispatch` 之前） | 世界 + 记忆 zip + run 图"进 `act` 前"那条 checkpoint 的位置（根图，`checkpoint_ns=""`） |
| task 世界快照 | `task_entry.begin_task` 末尾（同 v1 的 task 级位置） | 只有世界，不拍记忆、不写清单；按执行线分开存（C15） |
| 封存本局账 | 这一局结束（run 的 `act` 拿到 `EpisodeOutput` 之后）；run 中途出错时在 `run_error` 收场里 | 把本局的账复制进该局起点存档的 `trace@<branch>/`，记 `trace_sealed` 账 |

回放段内碰到的存档点一律不存、不记账（C16）。

`checkpoint_id`：run 级 `<run_id>@<branch>`；episode 级 `<episode_id>@<branch>`（`episode_id` 取 `dispatch` 将派的那个，
`dispatch` 是纯函数，P0 K-a 已证可重算）。task 世界快照不单独起 id，挂在它所属 episode 存档下。

## 三、落盘布局

```
checkpoints/
├── langgraph.sqlite
└── <run_id>/
    ├── branches.json
    ├── <checkpoint_id>/                  run 级或 episode 级
    │   ├── manifest.json
    │   ├── world.state
    │   └── trace@<branch>/               episode 级：每条跑过这一局的执行线各封一份（C14）
    └── worlds/<episode_id>/<task_id>@<branch>.state   task 开局的世界快照（C15）
memory/snapshots/<checkpoint_id>.zip
```

## 四、清单（相对 v1 的变化）

- 删：`episode_state` / `task_state` / `episode_input` / `task_input` / `outer`、`level="task"`。
- `level`：`"run" | "episode"`。
- 加：`run_ref: GraphRef | None`——episode 级时是 run 图"进 `act` 前"那条（`thread_id` + `checkpoint_id`，`ns` 恒为空）。
- 其余不变：`run_state`（run 级）、`world_file`、`memory_archive`、`last_event_uuid/ts`、`lineage`、`code`、`models`、`created_at`。

## 五、保存

`Checkpointer.save(level, state)`：世界 → 记忆 zip → （episode 级）从执行上下文取 run 图当前 checkpoint 位置，核 `next == ("act",)`
→ 分叉点 → 写清单 → `checkpoint_save`。`Checkpointer.snapshot_world(episode_id, task_id)`：写 `tasks/<task_id>.state` → `world_snapshot` 账。
失败口径同 v1：只记 `checkpoint_error`，run 照跑。`resuming` 与 `checkpoint_skipped` 删除。

## 六、trace 变更（需你确认）

| # | 变更 | 为什么 |
|---|---|---|
| T1 | 新账 `review_inject`（`form_kind`、`reply`）、`review_audit`（`overturned`、`note`）：每次调 reviewer 各记一条 | 插话可以连问多轮，现在只有最后那句 `human_note` 结构化落了账，中间几轮只在下一次 prompt 文本里；回放要按顺序喂回每一轮 |
| T2 | `read_object_memory` 的 `refs` 由 `place.key` 改为唯一键 `(episode_id, step, place.key)` | 同一格可有多条事件，`place.key` 取不回确定的那几条；其余读口的 `refs` 已是唯一的自然键（`(ep, step)`、`(ep, task_id)`、`episode_id`、知识 `source`） |
| T3 | 新账 `world_snapshot`（`task_id`、`path`） | task 世界快照的落点；回放到达时据此读档 |
| T4 | 删 `checkpoint_skipped` | v2 没有续跑段 |
| T5 | `leave_chapter` 的"先查再写"补 `read_episode_memory` 账 | 所有记忆读都要有 refs 可回放（C18） |
| T6 | 新账 `trace_sealed`（`checkpoint_id`、`count`） | 封存本局账的落点（C14） |
| T7 | `read_act_memory` 的 `query` 带上 `task_id`；`read_episode_memory` 的 `query` 带上 `order_by` | 账上记的就是交给记忆的查询原样（C17） |

不改的：`*_call` 已带 `prompt` 与 `raw`（及 token 数），`call_failed` 带异常类名与原文——够回放模型调用；
`sense_frame` 带完整观测（`status` / `facts` / `done` / `perceived` / `place` / `frame`），`get_action_space` 带动作名，`press_key` 带按键序列——够回放世界。

## 七、恢复

入口不变：`restore_run(manifest_path, build_branch, *, to_task: str | None = None)`。

**run 级**：同 v1——回档世界与记忆，原件改 `branch` 后从 `begin` 之后进图。

**episode 级**：回档世界与记忆 → 从 `run_ref` 读出 run"进 `act` 前"的状态 → `run_graph.update_state(新 thread, 值 + branch, as_node="plan_run")`，
核下一格是 `act` → `invoke(None)`。`act` 照常 `dispatch`、`begin_episode`、跑 episode 图，一切存档照常。**不再有图外续跑与交差。**

**到第 k 个 task（`to_task`）**：episode 级恢复 + 回放。

1. 定起点与磁带（C16）：起点 = task k 所在局在血缘上最近的那份 episode 存档；磁带 = 该存档里目标线封存的 `trace@<目标线>/`（C14，按血缘已含父线在这一局的前半段），
   切到 task k 的 `task_start` 之前。找不到就报错（不再退回 `tracelog/`）。
2. `build_branch` 按磁带装配（唯一装配点不变，磁带件都住 tools 层）：

| 被替换的 | 磁带件 | 回放时做什么 |
|---|---|---|
| brain 的 `LLMProvider` | `TapeProvider` | 按链路顺序吐出 `*_call` 里记的 `raw` 与 token 数，或按 `call_failed` 重抛同类异常；**先核 prompt 与账上逐字相同** |
| `GameTools` | `TapeGame` | `perceive_with_retry` 吐 `sense_frame` 还原的观测；`get_action_space` 吐账上的动作名；`execute` 不动模拟器，只核按键序列与 `press_key` 相同 |
| reviewer | `TapeReviewer` | 按序吐 `review_inject` / `review_audit` 记的回话（T1） |
| `MemoryTool` 的读 | `TapeMemory` | 按账上 `refs` 从记忆库直接取那几条（需要 memory 加"按键取"读口，见 §九）；写照常真写 |
| `TraceTool` | `TapeTrace` | 不落盘；每一笔拿去与磁带上的下一条比 `kind` 与正文（去掉 uuid / ts / 模型耗时这类每次都变的字段），对不上抛 `ReplayDiverged`。**读账**（harness 数本 task 已按键数、审一局时取整局账）返回"起点之前的账 + 磁带里已回放到的那些"，不能读空 |

3. 回放在图里正常跑：`act` → `begin_episode` → 拆解 → task 1…k−1 → task k 的 `begin_task`。
4. **切换**：`TapeTrace` 收到 task k 的 `task_start` 那一刻——按父线 `world_snapshot` 账上的路径读档回档世界、所有磁带件改走真件、
   先落 `checkpoint_restore`（带 `to_task`、分叉点 uuid），再落这条 `task_start`。之后一切照常。
5. 血缘分叉点 = 父线 task k 的 `task_start` 的前一条（D6），读侧拼接不用改。

记忆在切换时已等于父线 task k 开局时：episode 存档时的 zip + 回放段的真写（内容全由录下的输入算出）。

## 八、已知限制

| # | 限制 |
|---|---|
| L2 | 同一 run 的分支不能并行跑（记忆根只有一份） |
| L3 | 恢复会丢原分支存档之后写进记忆的内容 |
| L4 | 回放要求父线的 trace 完整在盘、且代码版本与父线一致（prompt 逐字比对；代码改了 prompt 就对不上，报 `ReplayDiverged`） |

v1 的 L1（续跑段不存档）不再存在。

## 九、模块影响

- **memory**：查询加 `order_by`（按元数据自然序）；act 记忆元数据加 `task_id`、查询可按它筛；写局摘要不变。另加按自然键取的读口（act `(ep, step)`、task `(ep, task_id)`、episode `episode_id`、object `(ep, step, place)`、knowledge `source`）——
  memory 是"可整体拷走"的模块，加的是通用的"按键取"，不含回放概念。
- **tools**：新增 `tools/replay/`（五个磁带件 + 磁带切片）。
- **brain**：不改（`TapeProvider` 实现 `LLMProvider` 协议，由装配点注入）。
- **harness**：run `act` 开头加一处存档、拿到 `EpisodeOutput` 后封存本局账；`run_error` 收场里封存；`begin_task` 末尾改为世界快照；
  五处 reviewer 调用各记一笔（T1）；`retrieve_act_memories` 改按 task 查、去掉手动筛；`read_plan_context` 改 `order_by`、去掉 `_in_execution_order`；
  `leave_chapter` 补读账；两处对象读改 refs；删 v1 的续跑、交差、`resuming`。决策逻辑不动。
- **build**：`build_real(..., replay=Tape | None)`。
- **trace / node_io**：T1–T4 的词表、渲染、契约。

## 十、保真核对（替换 v1 §九）

1. 真机短 run：≥1 run 级、≥1 episode 级存档，≥2 个 task 世界快照；
2. 两级存档各回档不开跑：世界字节、记忆 zip 哈希、run 状态读回一致；
3. 从 episode 存档**回放到第 2 个 task**：全程无 `ReplayDiverged`；切换时世界字节等于该 task 快照；记忆 zip 哈希等于父线在该 task 开局时的状态（为此核对脚本在 main 跑时额外拍一张对照快照）；
4. 恢复后跑到底，按血缘拼接 `node_io` 全过，父线 trace 一字节未变；
5. 改坏 `state_schema_hash` 被拒。

**离线也能验回放**：第 3 项只需父线 trace 与存档，切换前不调模型；到切换点就停的话一分钱不花。

## 十一、已确认（09-25，intent C10–C13）

| # | 问题 | 结论 |
|---|---|---|
| R1 | §六 T1–T4 这四处 trace 改动 | 按表改 |
| R2 | 回放段逐条比对父线的账（D7）要不要做 | 做：它就是回放的保真判据，代价只是比对 |
| R3 | memory 加"按键取"读口 | 加在 `MemoryToolPort`，信封按命名规则放 harness 侧 |
| R4 | v1 已实现的代码 | P6/P7 的续跑、交差、`resuming`、task 级完整存档删掉；分支、血缘、saver、世界存读、清单骨架保留 |
