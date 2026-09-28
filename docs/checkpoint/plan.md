# plan —— checkpointer：三级存档 + 图内恢复

> 流程位置：intent.md → spec.md → **plan.md** → PR → production
> 依据：`docs/checkpoint/spec.md`（2026-09-26）｜ 状态：已定（2026-09-26）

---

## 〇、排序原则

1. **先探测**：P0 验证 spec §九 的前四条断言。不过就停下回 spec——此时还一行主体代码没动，回放也还在。
2. **先删后加**：Q1 删回放与封存、Q2 删 intent C27 其余各项，之后每一步都在干净的底子上加。
3. **每步独立可验**：结束时 `pytest` 全过、fake run 的 `node_io` 全过，不留跑不起来的中间态。
4. **每步 = 一条 CHANGELOG 编号条目**；commit 等你说再做。
5. Q1 到 Q5 之间只有 run 级、episode 级恢复可用（task 级回放已删、图内恢复还没做），这是计划内的中间态。

## 一、步骤总览

| 步 | 内容 | 依赖 |
|---|---|---|
| P0 | 探测：嵌套子图的定位、读回、写入与续跑 ✅ 09-26，`p0-findings.md` | — |
| Q1 | 删回放与封存 ✅ 09-26，CHANGELOG 279 | P0 |
| Q2 | 删 intent C27 其余各项；episode 摘要内部自然序 ✅ 09-26，CHANGELOG 280–281 | Q1 |
| Q3 | trace 血缘自推；随机新线名与 `checkpoint_id`；checkpointer 不读 trace ✅ 09-26，CHANGELOG 282 | Q1 |
| Q4 | task 级完整存档 ✅ 09-26，CHANGELOG 283 | Q3 |
| Q5 | task 级图内恢复 ✅ 09-26，CHANGELOG 284 | Q4 |
| Q6 | 保真核对脚本与活文档 ✅ 09-26，CHANGELOG 285；真机两项待跑 | Q5 |

## 二、各步

### P0 探测

一次性探针，不进仓库：用 `tests/_fake_run.py` 的假大脑 / 假世界跑真实三张图，run 图挂 `SqliteSaver`（`durability="sync"`），在探针里包一层 `begin_task` 与 run 的 `act`。

**核**（spec §九 1–4）：
1. 在 `begin_task` 里用"当前命名空间去掉最后一段"从 `checkpoint_map` 推出 `episode_ref`，它指向 episode 图进 `act` 前那一条；
2. 按 `episode_ref` 用 saver 的 `get_tuple` 读回、按 `EpisodeRunState.model_fields` 取字段，与 episode 的 `act` 入参逐字段相等；
3. 新 thread 上 run 图 `update_state(as_node="plan_run")` → `invoke(None)`；run 的 `act` 里对 episode 图 `update_state(get_config(), 读回的状态, as_node="plan_episode")` 后 `next == ("act",)`，
   `invoke(None)` 第一个执行的是 `act`，`perceive` / `plan_episode` 没有重跑；
4. episode 图跑完，run 的 `act` 拿到 `EpisodeOutput`，run 图回到 `perceive`。

**产出**：重写 `docs/checkpoint/p0-findings.md`（逐条结论 + 实测到的命名空间与 `checkpoint_map` 样例）。

### Q1 删回放与封存

**删**
- `tools/replay/` 整目录；`build.py` 里包磁带件的那段与 `build_real(tape=…)`；`tools/brain_tool.py` 的 `tape` 参数。
- `restore.py`：`_plan_replay`、`_switch`、`_ReplayPlan`、`restore_run` / `open_branch` 的 `to_task` 与 `along`、`resume` 里对 `ReplayDiverged` 的处理、`OpenedBranch.tape`。
- `checkpointer.py`：`seal_episode`、`open_episode`、`paused`、`_open`、`SEALED_PREFIX`；run 的 `act` 与 `run_entry.record_run_error` 里的封存调用。
- `TraceKind.TRACE_SEALED` 及其渲染、`node_io` 契约、`DATAFLOW.md` 事件表行。
- `tests/test_checkpoint_replay.py`；`experiment/real_check/check_checkpoint.py` 里回放那几项（整脚本在 Q6 重写）。

**验收**：`pytest` 全过；fake run `node_io` 全过；`test_checkpoint_restore.py` 里 run 级、episode 级恢复照常通过；`grep -rn "replay\|Tape\|seal" pokemon_agent/` 无残留。

### Q2 删 intent C27 其余各项

**删 / 改**
- 问人两本账（`review_inject` / `review_audit`）保留，只把 `reviewing.py` 里"为回放"的说明改成"人在环可审计"。
- 两处对象读的 `refs` 回到 `place.key`。
- `MemoryToolPort.fetch`、`FromHarnessToMemoryToolFetchReq/Resp`、`MemoryTool.fetch`（及只为它存在的 store 辅助）。
- `FromHarnessToMemoryToolQueryEpisodeSummariesReq.order_by`；`read_plan_context`、`leave_chapter` 的传参与账上 query 串；`render.py` 读账说明表的那一行。
  `query_episode_summaries` 内部固定按 `episode_id` 自然序排（沿用 `_natural_key`）。
- act 记忆元数据的 `task_id`、`QueryActMemories` 的 `task_id` 条件；`retrieve_act_memories` 改为按 `episode_id` 查、按 `ActMemory.task_id` 筛；`read_act_memory` 的 query 串去掉 `task_id`。
- `leave_chapter` 的 `read_episode_memory` 账。
- `DATAFLOW.md` 同步。

**验收**：`pytest` 全过；fake run `node_io` 全过；fake run 的规划 prompt 与改前逐字相同（局数 < 10）；12 局的构造样本上 `query_episode_summaries` 返回 `ep1 … ep12`。

### Q3 trace 血缘自推

**改**
- `CheckpointMark` 留 `checkpoint_id` `level` `manifest_path` `stage`；`checkpoint_save` / `checkpoint_restore` 的 `checkpoint_id` 从 content 挪进 meta（checkpointer 的 `_meta` 与 `restore._note_restore` 组装），
  `checkpoint_restore` content 删 `parent_branch`、`parent_last_event_uuid`、`to_task`。渲染、`node_io`、`DATAFLOW.md` 同步。
- `TraceTool`：构造去掉 `lineage`；`read_events` 按 spec §六 四步从账本推血缘、每次现算；新增只读函数"本 run 的分支图"。
- 清单删 `lineage`、`last_event_uuid`、`last_event_ts`；删 `LineageLink`、`branches.py`、出口里的相关名字。
- `Checkpointer`：构造去掉 `lineage`；`save()` 删读分叉点那一步；`_new_id` 改为 `<前缀>@<branch>-<8 位 hex>`，删目录去重循环。
- `restore.open_branch`：新线名 `b-<6 位 hex>`；恢复状态只从清单与 saver / 世界 / 记忆快照读取，不查询 trace；`BuildBranch = Callable[[str], RunRuntime]`。
- `build.py`：`build_real` 去掉 `lineage`；`evals/e2e/runner/one.py` 的 `build_branch` 只收分支名。

**验收**：`pytest` 全过；`pokemon_agent/harness/checkpoint/checkpointer.py` 里没有 `read_events`；从 episode 级存档恢复后，新线按血缘读到的账与改前（外部传血缘）一致。当前恢复不再以 `checkpoint_save` 账作为前置校验；缺账只会影响 trace 读侧的血缘拼接。

### Q4 task 级完整存档

**改**
- 清单：`Level` 加 `task`，加 `task_id`、`episode_ref`，不变式按 spec §三。
- `Checkpointer`：`save(level, *, run_id, step, episode_id, task_id, state)`；task 级按 spec §四第 4 步推 `episode_ref` 并核父指针；task 级前缀 `<episode_id>.<task_id>`。
- `begin_task`：第一件事 `save(level="task")`，再写 `task_start`。
- 删 `snapshot_world`、`WORLDS_DIRNAME`、`_free`、`TraceKind.WORLD_SNAPSHOT` 及渲染、`node_io`；`checkpoint_error` 的 `stage` 取值去掉 `world_snapshot`、`seal`。

**验收**：fake run 跑完，每个 task 各有一个存档目录（清单 + 世界 + 记忆 zip）；每个 task 的账顺序是 `checkpoint_save` → `task_start`；`pytest` 全过。

### Q5 task 级图内恢复

**改**
- `Checkpointer`：`arm_resume(episode_id, task_id, state)` / `take_resume(episode_id)`；恢复后第一次 task 级 `save` 断言 `task_id` 与计划一致。
- run 的 `act`：`take_resume` 有值时不存 episode 级档、调 `episode_entry.resume_episode`，否则照旧。
- `episode_entry.resume_episode(deps, graph, state)`：spec §五。
- `restore.open_branch`：task 级按 `run_ref` 读 `RunState`、按 `episode_ref` 用 `get_tuple` 读 `EpisodeRunState`，`arm_resume`；`resume` 里 episode、task 两级共用"`update_state(as_node="plan_run")` → `invoke(None)`"。
- `harness/checkpoint` 新增 `list_checkpoints(root, run_id)`；出口同步。

**验收**：spec §九第 3–5 条；从第 2 个 task 的存档恢复跑到底，父线的账一字节未变；`pytest` 全过；按血缘拼读后 `node_io` 全过。

### Q6 保真核对与活文档

- `experiment/real_check/check_checkpoint.py` 按 spec §十 重写。
- 活文档：`docs/spec/checkpoint/`、`docs/spec/trace/`、`docs/spec/tools/`、`docs/spec/memory/`、`DATAFLOW.md` 里写到回放、封存、`branches.json`、世界快照、`fetch`、`order_by` 的地方。

**验收**：脚本离线部分（第 2、4、5 条）在 fake run 上过；真机部分（第 1、3 条，要调模型）由你跑。

## 三、测试与活文档（已定）

- **测试三处**：① Q3 重写 `tests/test_trace_branch.py`——只给分支名，血缘从账本推；② Q5 改写 `tests/test_checkpoint_restore.py`，加"从 task 级存档恢复跑到底"，含 spec §九第 5 条账序；
  ③ Q2 episode 摘要自然序的断言（原在 `fetch` 读口单测里）挪到 memory tool 的测试里。
- **`AGENTS.md` / `CLAUDE.md`**：写到回放或封存的段落在 Q6 一起改；ROADMAP H9 由你改。

## 四、风险与回退

- **P0 不过**：停在 P0，回 spec 重议；此时仓库未动。
- **旧存档读不了**：清单删了字段，旧 `manifest.json` 校验失败，报 `CheckpointCorrupt`。`evals/e2e` 的 `run_begin` 样本是现打包的，不受影响；其余旧存档作废。
- **task 级存档体积**：每个 task 一份记忆 zip，Q4 的 fake run 先量大小与耗时，真机数字在 Q6 第 1 条出来后再决定要不要限流。
