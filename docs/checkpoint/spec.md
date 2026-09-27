# spec —— checkpointer：三级存档 + 图内恢复

> 流程位置：intent.md → **spec.md** → plan.md → PR → production
> 状态：草稿（2026-09-26）
> 依据：`docs/checkpoint/intent.md` C1–C14

---

## 一、存档点

| 级别 | 位置 | 存什么 | 本层开局账 |
|---|---|---|---|
| run | `run_entry.new_run`：`game.reset` 之后、进 run 图之前 | 世界 + 记忆 zip + `RunState` 原件 | `run_start`（图内 `begin`） |
| episode | run 的 `act`：`dispatch` 之后、`run_episode` 之前 | 世界 + 记忆 zip + `run_ref` | `episode_start`（`begin_episode`） |
| task | `begin_task` 第一件事 | 世界 + 记忆 zip + `run_ref` + `episode_ref` | `task_start`（`begin_task`） |

**顺序约束**：三级都是**先存档（记 `checkpoint_save`）、后写本层开局账**。分叉点是 `checkpoint_save` 本身（§六），
开局账必须落在分叉点之后，否则恢复出的新线会在可见历史里看到父线的那条开局账，再加上自己重写的一条。
run、episode 两级现在已满足；task 级要把存档挪到 `task_start` 之前。

`config.CHECKPOINT_ENABLED` 为假时三级都不存（装配点不造 `Checkpointer`）。

## 二、落盘布局

```
checkpoints/
├── langgraph.sqlite                      saver（run 图与其嵌套子图的全部 checkpoint）
└── <run_id>/
    └── <checkpoint_id>/
        ├── manifest.json
        └── world.state
memory/snapshots/<checkpoint_id>.zip
```

没有 `branches.json`、`worlds/`、`trace@<branch>/`。

## 三、清单

```python
Level = Literal["run", "episode", "task"]

class GraphRef(BaseModel):          # saver 里的一条 checkpoint
    thread_id: str
    checkpoint_ns: str              # run 图恒为 ""；episode 图为它在 run 的 act 里的命名空间
    checkpoint_id: str

class CheckpointManifest(BaseModel):
    checkpoint_id: str
    level: Level
    run_id: str
    branch: str                     # 存档时所在的执行线
    episode_id: str | None          # episode / task 级
    task_id: str | None             # task 级
    run_state: RunState | None      # run 级
    run_ref: GraphRef | None        # episode / task 级
    episode_ref: GraphRef | None    # task 级
    world_file: str
    memory_archive: str
    code: CodeStamp
    models: dict[str, str]
    created_at: str
```

**不变式**（`model_validator`，违反即写清单的代码有 bug）：

| level | `run_state` | `run_ref` | `episode_ref` | `episode_id` | `task_id` |
|---|---|---|---|---|---|
| run | ✓ | — | — | — | — |
| episode | — | ✓ | — | ✓ | — |
| task | — | ✓ | ✓ | ✓ | ✓ |

删：`lineage`、`last_event_uuid`、`last_event_ts`、`LineageLink`。

## 四、保存

**构造**：`Checkpointer(root, run_graph, game, memory, trace, branch, models)`。去掉 `lineage`。
三层 runtime 持有同一个实例（不变）。

**`save(level, *, run_id, step, episode_id=None, task_id=None, state=None) -> str | None`**：

1. 生成 `checkpoint_id`（下文）；
2. 世界 → `<root>/<run_id>/<checkpoint_id>/world.state`；
3. 记忆 → `snapshot_memory(name=checkpoint_id)`；
4. 定位：
   - episode 级：`run_ref` = `_run_ref()`（现有实现不变：`checkpoint_map[""]`，核 `next == ("act",)`）；
   - task 级：`run_ref` 同上；`episode_ref` 取自同一个 `checkpoint_map`——当前命名空间（`get_config()` 的 `checkpoint_ns`，形如 `act:<id1>|act:<id2>`）
     去掉最后一段即 episode 图的命名空间 `act:<id1>`，它在 `checkpoint_map` 里对应的就是 episode 图进 `act` 前那一条；
     核 `saver.get_tuple(episode_ref).metadata["parents"][""] == run_ref.checkpoint_id`（公开 API；"下一格是 `act`"由位置保证，恢复写入后再核一次，见 P0 K2）。
     例外：恢复后第一个 task 的那一条是 `resume_episode` 用 `update_state` 写的，没有父指针（`metadata.source == "update"`），只核存在；
5. 写清单（原子写）；
6. 记 `checkpoint_save`（§六）。

失败口径不变：任一步抛错只记 `checkpoint_error`（带 `stage`：`world` / `memory` / `graph` / `manifest`），返回 None，run 照跑；`AssertionError` 原样上抛。

**`checkpoint_id`**：`<episode_id 或 run_id>@<branch>-<8 位 hex>`，随机部分取 `uuid.uuid4().hex[:8]`；task 级前缀用 `<episode_id>.<task_id>`。
不再检查目录是否已存在。例：`r1@main-0c5d11e8`（run 级）、`r1-ep2@main-3f9a1c07`（episode 级）、`r1-ep2.<task_id>@b-4c1e9a-5b07e2d4`（task 级，存在 `b-4c1e9a` 线上）。

**调用点**：
- run 级：`run_entry.new_run`（不变）；
- episode 级：run 的 `act`，非恢复模式时（§五）；
- task 级：`begin_task` 第一步，替换现在的 `snapshot_world`。

删：`snapshot_world`、`seal_episode`、`open_episode`、`paused`、`_open`、`_free`、`SEALED_PREFIX`、`WORLDS_DIRNAME`，以及 `save()` 里读 trace 取分叉点那一步。
**`Checkpointer` 不再调用 `trace.read_events`。**

## 五、恢复

**入口**：`restore_run(manifest_path, build_branch) -> run 级四元组`，= `resume(open_branch(...))`。去掉 `to_task`、`along`——恢复到哪一层由清单的 `level` 决定。

```python
BuildBranch = Callable[[str], RunRuntime]     # 分支名 -> 一套 runtime；不再收血缘与磁带
```

**`open_branch`**：
1. 读清单，核 `state_schema_hash`（不兼容 → `CheckpointIncompatible`）；
2. 定新线名 `b-<6 位 hex>`（`uuid4`，不读账），`build_branch(新线)` 装配；git commit 不同只告警（不变）；
3. 核分叉点：本 run 里 `checkpoint_id` 等于清单 id 的 `checkpoint_save` **恰好一条**，否则 `CheckpointNotFound`（经 `deps.trace.read_events({"run_id", "branch": 清单.branch, "checkpoint_id"})`）；
4. 读状态：run 级取 `run_state`；episode / task 级按 `run_ref` 经 `run_graph.get_state` 读 `RunState`；task 级另按 `episode_ref` 经 saver 的 `get_tuple` 读出 channel 值，
   按 `EpisodeRunState.model_fields` 取有的字段、缺席的 channel（从没写过的，如 `memory`、`output`）取模型缺省值，校验成模型；
5. 回档：`restore_memory(清单.memory_archive)` → `game.reset(...)` → `game.load_state(world.state)`（顺序不变）；
6. task 级：`ck.arm_resume(episode_id, task_id, episode_state)`；
7. 记 `checkpoint_restore`（新线第一条账，§六）。

**`resume`**（新 thread `<run_id>@<新线>`）：
- run 级：`invoke_run(RunState 改 branch)`，从 `begin` 进图（不变）；
- episode / task 级：`run_graph.update_state({"thread_id": 新thread}, RunState 各字段 + 新 branch, as_node="plan_run")`，核 `next == ("act",)`，`invoke(None)`（不变）。

**run 的 `act`**：

```
dispatched = dispatch(state)                                     # 纯函数，照常
resumed = ck.take_resume(episode_input.episode_id) if ck else None
if resumed is None:
    ck.save(level="episode", ...)                                 # 有存档器时
    outcome = episode_entry.run_episode(...)
else:
    outcome = episode_entry.resume_episode(deps, graph, resumed)  # 不存 episode 级档
```

恢复模式下**不存 episode 级档**：此刻世界与记忆已是 task k 开局的样子，按 episode 级存下去，清单写的是"进这一局前"，内容却是"局中间"，恢复它会错。

**`episode_entry.resume_episode(deps, graph, state: EpisodeRunState) -> EpisodeOutput`**（图外侧门，与 `run_episode` 并列）：

```
cfg = get_config()                                               # run 的 act 的执行上下文
graph.update_state(cfg, EpisodeRunState 各字段, as_node="plan_episode")
assert graph.get_state(cfg).next == ("act",)                    # 用 get_config()，update_state 的返回值不带 checkpointer
final = graph.invoke(None, {"recursion_limit": EPISODE_RECURSION_LIMIT}, context=deps)
return close(final, ...)
```

不写 `episode_start`（这一局的开局账在父线上，分叉点之前）。

**episode 的 `act` 与 `begin_task`**：不改，照常 `dispatch_task` → `run_task` → `begin_task`。`begin_task` 先 `save(level="task")`（新线自己的存档），再写 `task_start`。

**`Checkpointer` 的恢复计划**（C9："恢复只住在 checkpointer 与各层 `act` 里"）：
- `arm_resume(episode_id, task_id, state)`：`open_branch` 调一次；
- `take_resume(episode_id) -> EpisodeRunState | None`：run 的 `act` 调；有计划时断言 `episode_id` 相同，交出后清空；
- 恢复后第一次 `save(level="task")` 断言 `task_id` 等于计划里的（`dispatch_task` 重算出的就是目标 task）。

## 六、trace

**meta**：`checkpoint_save`、`checkpoint_restore` 两本账的 meta 加 `checkpoint_id`；其余账不变（`run_id`、`branch` 仍由落盘层盖）。

| 账 | meta | content |
|---|---|---|
| `checkpoint_save` | `source` `episode_id` `task_id` `step` **`checkpoint_id`** | `level` `manifest_path` |
| `checkpoint_restore` | 同上 | `level` `manifest_path` |
| `checkpoint_error` | 不变 | `checkpoint_id` `stage` `error`（不变） |

`checkpoint_id` 从 content 挪进 meta，不两处放。`checkpoint_restore` 的 content 删 `parent_branch`、`parent_last_event_uuid`、`to_task`：父线由分叉点推出，其余不再存在。
task 级存档的 meta：`episode_id`、`task_id` 取该 task，`step` = `start_step`；run、episode 级沿用现在的 `_meta`。

**`CheckpointMark`**：留 `checkpoint_id` `level` `manifest_path` `stage`；删 `world_path` `count` `parent_branch` `parent_last_event_uuid` `to_task`。`level` 取值加 `task`。

**`TraceKind`**：删 `WORLD_SNAPSHOT`、`TRACE_SEALED`。问人两本账 `REVIEW_INJECT` / `REVIEW_AUDIT` 保留（人在环的审计依据）。渲染、`node_io` 契约、`docs/spec/DATAFLOW.md` 事件表同步。

**血缘由 TraceTool 从账本推**：构造参数去掉 `lineage`，只留 `run_id` 与 `branch`。`read_events(meta)` 在 meta 不带 `branch` 时：

1. 读本 run 全部账（store 层按 `{"run_id"}` 筛，不拼接）；
2. 从本线往上走：本线的 `checkpoint_restore`（恰好一条）→ 同 `checkpoint_id` 的 `checkpoint_save`（恰好一条）→ 父线 = 它的 `branch`，分叉点 = 它的 `(ts, uuid)`；重复直到 `main`；
3. 可见的账 = 本线全部 + 每个祖先在各自分叉点及之前的账；
4. 再按调用方的 `meta` 交集筛，按 `(ts, uuid)` 排序返回。

每次调用现算，不缓存（盘上账本唯一真相）。meta 为空或自带 `branch` 时行为不变（不拼接）。

**分支图**：本 run 的每条 `checkpoint_restore` 是一条边"新线 → 父线 @ 分叉点"，节点是出现过的所有 `branch`。放在 `tools/trace/` 一个只读函数里，给核对脚本与观测台用。

## 七、删除

| 删 | 位置 | 行为上的后果 |
|---|---|---|
| 回放 | `tools/replay/`（五个磁带件、`Tape`、`ReplayDiverged`）；`build_real` 的 `tape`、`BrainTool.build` 的 `tape`；`restore.py` 的 `_plan_replay` / `_switch` | 无（由图内恢复取代） |
| 分支登记 | `harness/checkpoint/branches.py`、`LineageLink`；`build_real` 与 `Checkpointer` 的 `lineage` | 血缘改由 TraceTool 推 |
| 封存本局账 | `seal_episode` 及其两个调用点（run 的 `act`、`record_run_error`） | 无 |
| 世界快照账 | `snapshot_world`、`world_snapshot` 账 | 并入 task 级存档 |
| 对象读 refs 唯一键 | 两处对象读的 `refs` 回到 `place.key` | 账上的 refs 不再能唯一定位事件 |
| 按自然键取的读口 | `MemoryToolPort.fetch`、`FromHarnessToMemoryToolFetchReq/Resp`、`MemoryTool.fetch` | 无消费者 |
| `order_by` | `FromHarnessToMemoryToolQueryEpisodeSummariesReq.order_by`；`read_plan_context`、`leave_chapter` 的传参与账上 query 串 | `query_episode_summaries` 内部固定按 `episode_id` 自然序排（数字段按数值比，`ep2 < ep10`），不开参数 |
| act 记忆的 `task_id` 元数据 | `store_act_memory` 的元数据、`QueryActMemories` 的 `task_id` 条件 | `retrieve_act_memories` 回到按 `episode_id` 查、harness 按 `ActMemory.task_id` 筛 |
| 所有记忆读都记账 | `leave_chapter` 的 `read_episode_memory` 账；`read_act_memory` 的 query 串里的 `task_id` | 回到只有检索性质的读记账 |

## 八、模块影响

- **harness/checkpoint**：`manifest.py`（§三）、`checkpointer.py`（§四、恢复计划）、`restore.py`（§五）；删 `branches.py`；加 `list_checkpoints(root, run_id) -> list[CheckpointManifest]`（按创建时间排，给人挑存档用）。出口同步。
- **harness/run**：`act` 的恢复分支；`record_run_error` 不再封存。
- **harness/episode**：`episode_entry.resume_episode`。
- **harness/task**：`begin_task` 先存档后写 `task_start`。
- 对象读、`retrieve_act_memories`、`read_plan_context`、`leave_chapter`：§七。
- **memory / tools/memory_tool.py**：删 `fetch`、`order_by`、act 的 `task_id` 元数据；`query_episode_summaries` 内部固定按 `episode_id` 自然序排（沿用现有 `_natural_key`）。
- **tools/trace**：血缘自推、分支图函数、渲染与词表（§六）。
- **tools/replay**：整目录删。
- **brain**：不改（`BrainTool.build` 去掉 `tape` 在 tools 层）。
- **build.py**：`build_real` 去掉 `lineage`、`tape`。
- **evals/e2e/runner/one.py**：`build_branch` 改成只收分支名。
- **experiment/real_check/check_checkpoint.py**：按 §十 重写。
- **测试**：`test_checkpoint_replay.py` 随回放删除；`test_checkpoint_restore.py` 要改写（plan 阶段再问）。

## 九、开工前提（探测）

**P0 已通过第 1–4 条**（`docs/checkpoint/p0-findings.md`），第 5 条依赖 Q4 的存档位置，在 Q5 验收。以下为原始依据与断言。LangGraph 源码里的依据：`get_state` / `update_state` 只在"config 带嵌套命名空间、**且没带 checkpointer**"时
转派给同名子图（`pregel/main.py:1405-1416`、`1624-1638`）；在 run 的 `act` 节点里 `get_config()` 带着父图的 checkpointer，所以会直接作用在该命名空间上。
反过来，在图外按 `episode_ref` 调 `episode_graph.get_state` 不可用：episode 图没带 saver 时报 `No checkpointer set`，带了也会被转派给名为 `act` 的子图而报错——所以存档核对与 §五第 4 步的读回都走 saver 的 `get_tuple`。

fake run 最小用例，断言：
1. 存档时推出的 `episode_ref` 指向 episode 图进 `act` 前那一条（父指针判据）；
2. 按 `episode_ref` 用 `get_tuple` 读回的 `EpisodeRunState` 与存档时逐字段相等；
3. `resume_episode` 里写入后 `next == ("act",)`；`invoke(None)` 第一个执行的是 `act`，`perceive` / `plan_episode` 没有重跑（数调用次数）；
4. episode 图跑完，run 的 `act` 拿到 `EpisodeOutput`，run 图回到 `perceive`；
5. 新线的账顺序：`checkpoint_restore` → `checkpoint_save(task)` → `task_start`，可见历史里 `episode_start` 与目标 task 的 `task_start` 各只一条。

前四条过了再动主体代码。

## 十、保真核对（`check_checkpoint.py`）

1. 真机短 run：≥1 run 级、≥1 episode 级、≥2 task 级存档；记录每次 task 级存档的记忆 zip 大小与耗时；
2. 三级各恢复不开跑：世界字节、记忆 zip 哈希、`RunState`（task 级再加 `EpisodeRunState`）与存档时一致；
3. 从第 2 个 task 的存档恢复并跑到底：新线账顺序同 §九第 5 条；父线的账一字节未变；
4. 仅凭 trace 画出的分支图与实际恢复过程一致；按血缘拼读后 `node_io` 全过；
5. 改坏 `state_schema_hash` 被拒；删掉某份存档对应的 `checkpoint_save` 后恢复被拒。

## 十一、已知限制

| # | 限制 |
|---|---|
| L1 | 同一 run 的分支不能并行跑（记忆根只有一份） |
| L2 | 恢复会抹掉父线最后一个存档点之后写进记忆活库的内容 |
| L3 | 每个 task 一份世界文件 + 一份记忆 zip，存档体积随 task 数线性增长；§十第 1 条量出来再定要不要限流 |
| L4 | 代码版本不同只告警；只有状态结构变了才拒绝 |
