# checkpoint —— 三级存档与图内恢复

> 最后更新：2026-09-26 ｜ 代码：`pokemon_agent/harness/checkpoint/`、`pokemon_agent/tools/trace/lineage.py` ｜
> 设计来历：`docs/checkpoint/{intent,spec,plan,p0-findings}.md`、CHANGELOG 275–285

一句话：run 开局、每局开派前、每个 task 开局各存一份"此刻的全部现场"（世界、记忆整根、图状态的原件或定位）。
从任意一份存档可以恢复出一条**新执行线**（同一 `run_id`、新 `branch`），run 图与 episode 图在图内回到
"进 `act` 前"，从那一层接着跑——不回放、不重跑已完成的 task。trace 不回滚，只追加；
分支关系从账本自己推出来，不另存登记表。

## 一、存档点

| 级别 | 调用位置 | 内容 |
|---|---|---|
| run | `run_entry.new_run`：`game.reset` 之后、进 run 图之前 | 世界 + 记忆 zip + `RunState` 原件 |
| episode | run 的 `act`：`dispatch` 之后、跑这一局之前（恢复模式下不存） | 世界 + 记忆 zip + `run_ref` |
| task | `task_entry.begin_task` 第一件事 | 世界 + 记忆 zip + `run_ref` + `episode_ref` |

三级都**先存档（记 `checkpoint_save`）、后写本层开局账**：存档账就是从它恢复出的新线的分叉点，开局账要落在
分叉点之后。开关：`config.CHECKPOINT_ENABLED`（关时装配点不造 `Checkpointer`）。

两个定位都从执行上下文的 `checkpoint_map` 取：`""` → run 图（根图）进 `act` 前那条，存前核 `next == ("act",)`；
当前命名空间（形如 `act:<id1>|act:<id2>`）去掉最后一段 → episode 图进 `act` 前那条，核它在 saver 里的父指针等于
`run_ref`（恢复后第一个 task 那条是 `update_state` 写的，没有父指针，只核存在）。

任一步失败只记 `checkpoint_error`（带 `stage`：world / memory / graph / manifest），run 照跑；`AssertionError`
照常上抛。**存档不读 trace。**

## 二、落盘

```
<checkpoint_root>/                          缺省 = 启动目录下的 checkpoints/
├── langgraph.sqlite                        图状态库（一条执行线一个 thread：<run_id>@<branch>）
└── <run_id>/
    └── <checkpoint_id>/                    <episode_id 或 run_id>@<branch>-<8 位 hex>；task 级前缀 <episode_id>.<task_id>
        ├── manifest.json
        └── world.state
<memory_root>/snapshots/<checkpoint_id>.zip
```

`checkpoint_id` 的随机段不看盘上已有什么，同一 run 里多次存档各不相同。清单与账里的路径（`memory_archive`、
`manifest_path`）一律**相对进程启动目录**、分隔符 `/`（`manifest.launch_relative`）；`world_file` 相对清单所在目录。

清单 `CheckpointManifest`（`manifest.py`）：`checkpoint_id`、`level`（run / episode / task）、`run_id`、`branch`、
`episode_id`、`task_id`、`run_state`、`run_ref`、`episode_ref`、`world_file`、`memory_archive`、`code`（git commit、
工作区是否干净、`state_schema_hash`）、`models`、`created_at`。级别与内容的不变式：run 级只带 `run_state`；
episode 级带 `episode_id` + `run_ref`；task 级再加 `task_id` + `episode_ref`。
`list_checkpoints(root, run_id)` 按创建先后列出能读的清单。

## 三、分支与血缘

- 分支名 `main`；每恢复一次开一条随机名的新线 `b-<6 位 hex>`（名字要在装配前定，不读账）。
- trace `meta.branch` 由落盘层盖章。`checkpoint_save` / `checkpoint_restore` 的 meta 另带 `checkpoint_id`：
  新线第一条账是 `checkpoint_restore`，同 id 的 `checkpoint_save` 在哪条线上，那条线就是父线，它本身（含它）
  就是分叉点。
- `tools/trace/lineage.py`：`lineage_of(账, branch)` 由近到远推血缘，`branch_graph(账, run_id)` 画分支图
  （每条恢复账一条边）。`TraceTool.read_events` 在 meta 不带 `branch` 时按血缘拼：本线全部 + 各祖先截至各自
  分叉点；血缘每次现推，不缓存。`node_io.branch_view` 用同样的规则各推一遍，互为对照。
- 同一个 task 在父线与新线各有一份账，读侧按分叉点截断，不按业务键去重。

## 四、恢复

`restore_run(manifest_path, build_branch)` = `resume(open_branch(...))`；`build_branch(分支名) -> RunRuntime`
由调用方给（真机包一层 `build_real(..., branch=)` 取 `harness.deps`）。

`open_branch`：读清单、核 `state_schema_hash`（不符 → `CheckpointIncompatible`）→ 起新线名、装配 →
核父线上这份存档的 `checkpoint_save` 恰好一条（否则 `CheckpointNotFound`）→ 读回图状态 →
回档记忆、世界 → 记 `checkpoint_restore`。前三步失败时一笔账都没写。git commit 不同只告警。

| 从哪恢复 | 做法 |
|---|---|
| run 级 | 原件改上新 `branch`，从 `begin` 之后进图 |
| episode 级 | run 图进 `act` 前的值（按 `run_ref` 读）以 `plan_run` 的名义写进新 thread → `invoke(None)`；run 的 `act` 照常派这一局、照常存档 |
| task 级 | 同 episode 级进 run 图；另按 `episode_ref` 用 saver `get_tuple` 读回 `EpisodeRunState`（缺席的 channel 取缺省值），放进 `Checkpointer` 的恢复计划（`arm_resume`）。run 的 `act` 取到计划（`take_resume`，取一次即清）时不存 episode 级档，改调 `episode_entry.resume_episode`：在 `get_config()` 上对 episode 图 `update_state(as_node="plan_episode")`、核下一格是 `act`、`invoke(None)`。episode 的 `act` 与 `begin_task` 照常执行，新线在目标 task 开局存下自己的 task 级档；恢复后第一次 task 级存档断言开局的就是目标 task |

图外按嵌套命名空间调 `episode_graph.get_state` 不可用（episode 图没带 saver 会报 `No checkpointer set`，带了也会被
转派给名为 `act` 的子图），所以读 episode 状态一律直接问 saver；节点内的 `get_config()` 带着父图的 saver，写入与核对
都用它（`update_state` 的返回值不带 saver）。依据见 `docs/checkpoint/p0-findings.md`。

恢复后从恢复点起是全新执行：模型可以给出与父线不同的输出，不承诺结果一样。

## 五、trace 里的账

| kind | 何时 | meta 另带 | 正文 |
|---|---|---|---|
| `checkpoint_save` | 存档落好（先于本层开局账） | `checkpoint_id` | `level`、`manifest_path` |
| `checkpoint_restore` | 新执行线第一条 | `checkpoint_id` | `level`、`manifest_path` |
| `checkpoint_error` | 存档某一步失败 | — | `checkpoint_id`、`stage`、`error` |

存档一族不进 `node_io` 的活动流（旁路，条数随存档开关浮动）。问人两本账（`review_inject` / `review_audit`）
与存档无关，见 `harness/reviewing.py`。

## 六、已知限制

| # | 限制 |
|---|---|
| L1 | 同一 run 的分支不能并行跑（记忆根只有一份） |
| L2 | 恢复会抹掉父线最后一个存档点之后写进记忆活库的内容 |
| L3 | 每个 task 一份世界文件 + 一份记忆 zip，存档体积随 task 数线性增长 |
| L4 | 代码版本不同只告警；只有状态结构变了才拒绝 |

## 七、怎么验

- `tests/test_checkpoint_restore.py`：三级存档的形状与账序；run / episode 级各恢复一次跑到底；分支套分支；
  从 task 级存档恢复直达该 task（账序、不重开这一局、开局账各一条）；按血缘 `node_io` 全过。
- `tests/test_trace_branch.py`：只给分支名，血缘与分支图从账本推。
- 真机：`python -m experiment.real_check.check_checkpoint`（维度 3，见 `docs/spec/experiment/SPEC.md`）。
