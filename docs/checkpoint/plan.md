# plan —— checkpointer v2（两级存档 + 回放到 task）

> 流程位置：intent.md → spec.md → **plan.md** → PR → production
> 依据：`docs/checkpoint/spec.md` v2（09-25 定稿，intent C1′、C7–C18）｜ 起草：2026-09-25 ｜ 状态：**已定稿（09-25）**
> v1 的 plan（P0–P8，CHANGELOG 229–237）存档在 `plan-v1.md`；v2 在其上改，不回退已保留的部分（分支、血缘、saver、世界存读、清单骨架）

---

## 〇、排序原则

1. **先删后加**：Q1 先把 v1 里 v2 不要的东西删干净，后面每一步都在干净的底子上加。
2. **先改不涉及存档的基础**（Q2 记忆查询、Q3 trace），再改存档点（Q4、Q5），最后做回放（Q6、Q7）。
3. **每步独立可验**：结束时 `pytest` 全过、fake run 的 `node_io` 全过，不留跑不起来的中间态。
4. **每步 = 一条 CHANGELOG 编号条目**；commit 等你说再做。
5. 测试写三处：Q4、Q7 的用法示范，Q6 的读口单测（09-25 定）。

## 一、步骤总览

| 步 | 内容 | 状态 | 依赖 |
|---|---|---|---|
| Q1 | 清理 v1：图外续跑、交差、`resuming`、`checkpoint_skipped`、task 级完整存档 | ✅ 09-25，与 Q4 合并，CHANGELOG 238 | — |
| Q2 | 记忆查询规矩：act 记忆加 `task_id`、查询加 `order_by`（自然序）、harness 去掉二次筛与排 | ✅ 09-25，CHANGELOG 239 | — |
| Q3 | 补 trace：T1 reviewer 两本账、T2 对象 refs 唯一键、T5 `leave_chapter` 读账、T7 query 写法 | ✅ 09-25，CHANGELOG 240（T7 在 239 一并做了） | Q2 |
| Q4 | episode 级存档挪到 run `act` 开头；episode 级恢复改为图内正常跑 | ✅ 09-25，与 Q1 合并，CHANGELOG 238 | Q1 |
| Q5 | task 世界快照（按执行线）+ 封存本局账（`trace_sealed`） | ✅ 09-25，CHANGELOG 241 | Q4 |
| Q6 | memory 按自然键取的读口 | ✅ 09-25，CHANGELOG 242 | Q2 |
| Q7 | 回放：`tools/replay/` 五个磁带件、磁带切片、切换点、`restore_run(to_task=…)` | ✅ 09-25，CHANGELOG 243 | Q3、Q5、Q6 |
| Q8 | 保真核对脚本改版 + 活文档同步 | 🟡 09-25，CHANGELOG 244：脚本与文档已写；**真机未跑；AGENTS.md / CLAUDE.md / ROADMAP H9 的文字待你看** | Q7 |

---

## Q1 清理 v1

**删**
- `restore.py`：`_finish_episode`、`_finish_task`、`_hand_back_run`、`graph_values`（Q4 再按需要加回精简版）；`restore_run` 暂时只保留 run 级路径，episode 级由 Q4 重写。
- `Checkpointer`：`resuming`、`RESUME_STRETCH`、`save(level="task")` 与 `task_input` / `outer[1]` 相关代码。
- `TraceKind.CHECKPOINT_SKIPPED` 及其渲染、`node_io` 契约（T4）。
- 清单：`task_state` / `task_input` / `level="task"`。
- `task_entry.begin_task` 末尾的完整存档调用（Q5 换成世界快照）。
- 测试：`test_checkpoint_restore.py` 中 episode / task 级恢复用例暂时去掉（Q4、Q7 重写）；`check_checkpoint.py` 暂标"待 Q8 改版"。

**验收**：`pytest` 全过；fake run 三种场景 `node_io` 全过；run 级存档恢复用例照常通过。

## Q2 记忆查询规矩（C17）

- `MemoryTool.store_act_memory` 元数据加 `task_id`；`FromHarnessToMemoryToolQueryActMemoriesReq` 加可选 `task_id` 条件。
- 各查询信封加可选 `order_by: str | None`；memory 侧按该元数据字段**自然序**排序（数字段按数值比），缺省维持现有确定序。
- `task/perceive/retrieve_act_memories`：改为按 `episode_id + task_id` 查，删手动筛。
- `run/perceive/read_plan_context`：改为 `order_by="episode_id"`，删 `_in_execution_order`。
- `query_episode_summaries` 现有的字典序排序改为自然序（修 `ep10 < ep2`）。

**验收**：fake run 的 prompt 与改前逐字相同（只要局数 < 10）；新增的自然序在 12 局的构造样本上顺序正确（放进 Q6 的读口单测里一起测）。

## Q3 补 trace（T1、T2、T5、T7）

- T1：`TraceKind.REVIEW_INJECT`（`form_kind`、`reply`）、`REVIEW_AUDIT`（`overturned`、`note`）；harness 五处 reviewer 调用各记一笔（提一个小函数，每处一行）。
- T2：两处对象读的 `refs` 改为 `"(episode_id, step, place.key)"`。
- T5：`leave_chapter` 的查询补 `read_episode_memory`。
- T7：`read_act_memory` 的 `query` 带 `task_id`；`read_episode_memory` 带 `order_by`。
- 渲染、`node_io` 契约、`docs/spec/DATAFLOW.md` 事件表同步。

**验收**：fake run 各场景 `node_io` 全过；带插话的 fake reviewer 场景下每次 inject / audit 各有一条账。

## Q4 episode 级存档与恢复（D1）

- run `act` 节点第一件事调 `checkpointer.save(level="episode", state)`；`begin_episode` 末尾的存档删掉。
- 清单：`run_ref: GraphRef`（run 图"进 `act` 前"那条，根图）替代 `outer`；删 `episode_state` / `episode_input`。
- 恢复：回档世界与记忆 → 读 `run_ref` 的值 → `run_graph.update_state(新 thread, 值 + branch, as_node="plan_run")`，核下一格是 `act` → `invoke(None)`。
- 测试 `test_checkpoint_restore.py`：fake run 从 run 级、episode 级存档各恢复一次跑到底；新线首条账是 `checkpoint_restore`；父线的账逐字节不变；按血缘拼接后 `node_io` 全过；新线上 episode 存档照常产生。

**验收**：上述测试通过；`pytest` 全过。

## Q5 task 世界快照 + 封存本局账（C14、C15）

- `Checkpointer.snapshot_world(episode_id, task_id)`：写 `checkpoints/<run_id>/worlds/<episode_id>/<task_id>@<branch>.state`，记 `world_snapshot`（T3）。`begin_task` 末尾调它。
- `Checkpointer.seal_episode(episode_id)`：把本局 episode 存档之后、本执行线的账复制进该存档 `trace/`，记 `trace_sealed`（T6）。调用点：run `act` 拿到 `EpisodeOutput` 之后；`run_entry.record_run_error` 里。
- 两本新账的渲染与 `node_io` 契约。

**验收**：fake run 跑完后每个 episode 存档都有 `trace/`，内容与 `tracelog/` 里本局的账逐文件相同；`worlds/` 下每个 task 一份快照；中途出错的场景也封存了已写出的部分。

## Q6 memory 按键取的读口（C12）

- `MemoryToolPort` 加按自然键取：act `(episode_id, step)`、task `(episode_id, task_id)`、episode `episode_id`、object `(episode_id, step, place)`、knowledge `source`；信封按命名规则放 harness 侧。
- 单测：每类写几条，按键取回与查询结果逐字段相同；顺序按给定键的顺序；不存在的键报错；Q2 的自然序样本。

**验收**：单测通过。

## Q7 回放（C7–C9、C11、C16）

- `tools/replay/`：`TapeProvider`、`TapeGame`、`TapeReviewer`、`TapeMemory`、`TapeTrace`，外加磁带切片（起点存档、按血缘拼账、切到目标 task）。
- `TapeTrace` 的读账返回"起点之前的账 + 已回放到的账"。
- 切换：`TapeTrace` 收到目标 task 的 `task_start` 时读世界快照、磁带件改走真件、先记 `checkpoint_restore` 再记 `task_start`。
- 回放段内 `Checkpointer` 不存、不记账。
- `build_real(..., replay=Tape | None)`；`restore_run(manifest_path, build_branch, *, to_task=None)`。
- 测试（`test_checkpoint_replay.py`）：fake run 上回放到第 2 个 task，全程无 `ReplayDiverged`，切换后跑到底；从新线再回放出一条（分支套分支）；故意改一条录下的输出，确认报 `ReplayDiverged`。

**验收**：测试通过；`pytest` 全过。

## Q8 保真核对与文档

- `check_checkpoint.py` 按 spec v2 §十 改版（含离线回放到第 2 个 task 的比对）。
- 活文档：`docs/spec/checkpoint/SPEC.md` 重写；`harness` / `trace` / `memory` / `DATAFLOW` / `experiment` 各 SPEC 同步；`AGENTS.md` 若有目录变化先给你看。

**验收**：你在本机真机跑 `check_checkpoint` 全过（沙箱连不上模型接口）。
