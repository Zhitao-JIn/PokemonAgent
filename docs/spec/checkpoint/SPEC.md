# checkpoint —— 两级存档、恢复与回放到任意 task

> 最后更新：2026-09-25 ｜ 代码：`pokemon_agent/harness/checkpoint/`、`pokemon_agent/tools/replay/` ｜
> 设计来历：`docs/checkpoint/{intent,spec,plan}.md`（v2）、CHANGELOG 229–243

一句话：run 开局存一份、每局开派前存一份"此刻的全部现场"（世界、记忆整根、run 图状态）；每个 task
开局只存一份世界快照；每局结束把这一局的账封存进这一局的存档。从任意一份存档可以恢复出一条**新执行线**
（同一 `run_id`、新 `branch`）在图里接着跑；要从某局中间的 task 开始，就从这一局的存档**回放**到那个 task。
trace 不回滚，只追加。

## 一、存档点

| 存什么 | 调用位置 | 内容 |
|---|---|---|
| run 级存档 | `run_entry.new_run`：`game.reset` 之后、进 run 图之前 | 世界 + 记忆 zip + `RunState` 原件 |
| episode 级存档 | run 的 `act` 节点一开始（`dispatch` 算出将派的局之后、跑这一局之前） | 世界 + 记忆 zip + run 图"进 `act` 前"那条 checkpoint 的位置（`run_ref`，根图） |
| task 世界快照 | `task_entry.begin_task`：写完 `task_start` 之后 | 只有世界 |
| 封存本局的账 | run 的 `act` 拿到本局结算之后；`run_entry.record_run_error` 里 | 起点存档之后、本执行线的账逐条写进起点存档的 `trace@<branch>/` |

两级存档都**不嵌在任何 `act` 里**：run 级在进图前，episode 级时 run 图是根图、正停在进 `act` 前
（执行上下文的 `checkpoint_map[""]` 就是它，存前核 `next == ("act",)`）。开关：`config.CHECKPOINT_ENABLED`。

任一步失败只记 `checkpoint_error`（带 `stage`：world / memory / graph / manifest / world_snapshot / seal），
run 照跑；`AssertionError` 照常上抛。回放段里 `Checkpointer.paused` 为真，三个存档点都不存、不记账。

## 二、落盘

```
<checkpoint_root>/                          缺省 = 启动目录下的 checkpoints/
├── langgraph.sqlite                        图状态库（一条执行线一个 thread：<run_id>@<branch>）
└── <run_id>/
    ├── branches.json                       分支登记表（恢复过才有）
    ├── <checkpoint_id>/                    run 级（<run_id>@<branch>）或 episode 级（<episode_id>@<branch>）
    │   ├── manifest.json
    │   ├── world.state
    │   └── trace@<branch>/                 episode 级：跑过这一局的每条执行线各封一份
    └── worlds/<episode_id>/<task_id>@<branch>.state    task 开局的世界快照
<memory_root>/snapshots/<checkpoint_id>.zip
```

清单 `CheckpointManifest`（`manifest.py`）：`level`（run / episode）、`run_id`、`branch`、`lineage`、
`episode_id`（episode 级：将派的那一局）、`run_state`（run 级）、`run_ref`（episode 级）、`world_file`、
`memory_archive`、`last_event_uuid` / `last_event_ts`（存档时本执行线最后一条账）、`code`（git commit、
工作区是否干净、`state_schema_hash`）、`models`、`created_at`。

## 三、分支与血缘

- 分支名 `main`，恢复一次开一条 `b1`、`b2`…；`branches.json` 记父线与完整血缘（由根到父的
  `LineageLink(branch, fork_uuid, fork_ts, checkpoint_id)`）。
- trace `meta.branch` 由落盘层盖章；`TraceTool.build(branch=…, lineage=…)` 的 `read_events` 按血缘拼：
  各祖先截至各自分叉点 + 本线全部。
- `node_io.branch_view(events, branch)` 从账本身读血缘（新线的 `checkpoint_restore` 带父线与分叉点），逐线核对。

## 四、恢复

`restore_run(manifest_path, build_branch, *, to_task=None, along=None)` = `resume(open_branch(...))`。
`build_branch(分支名, 血缘, 磁带) -> RunRuntime` 由调用方给（真机包一层 `build_real(..., branch=, lineage=, tape=)`
取 `harness.deps`）。

| 从哪恢复 | 做法 |
|---|---|
| run 级 | 回档世界与记忆 → 记 `checkpoint_restore` → 原件改上新 `branch`，从 `begin` 之后进图 |
| episode 级 | 回档 → 记 `checkpoint_restore` → run 图进 `act` 前的值以 `plan_run` 的名义写进新 thread → `invoke(None)`，`act` 照常派这一局 |
| 到某个 task（`to_task`） | episode 级回档 + 回放（下一节）；`checkpoint_restore` 等切换时才记 |

状态结构哈希不符 → `CheckpointIncompatible`（不登记分支）；git commit 不同只告警。

## 五、回放（`tools/replay/`）

- **磁带**：起点存档里 `along`（缺省 = 存档所在执行线）封存的 `trace@<along>/`，切到这一局目标 task 的
  `task_start` 之前。新线的父线 = 目标 `task_start` 前一条账所属的线，血缘截到那里。
- **磁带件**（装配点在有磁带时把真件包成它们）：

| 顶替 | 回放时做什么 |
|---|---|
| `TapeProvider`（brain 的每个 provider） | 按序吐录下的原文 / 重抛录下的同名失败，先核 prompt 逐字相同 |
| `TapeGame` | 观测、动作空间取自磁带；按键不动模拟器；录下的感知耗尽照样抛 |
| `TapeMemory` | 读口按账上的 `refs` 经 `MemoryToolPort.fetch` 取回；写照常真写 |
| `TapeReviewer` | 按序吐录下的插话 / 审的回话 |
| `TapeTrace` | 不落盘；每一笔与磁带比 `kind`、正文、`meta`；读账返回已放过的 |

- 模型调用账、`call_failed` / `summary_parse_error` 与存档一族不逐条比；其余每一笔对不上即 `ReplayDiverged`。
- **切换**：`TapeTrace` 收到目标 `task_start` → 读该 task 的开局世界快照 → 存档器恢复 → `open_episode`
  指定这一局的起点存档（本局结束时新线的账封进它的 `trace@<新线>/`）→ 记 `checkpoint_restore`（正文带 `to_task`）
  → 落这条 `task_start`，此后一切照常。

## 六、trace 里的账

| kind | 何时 | 正文 |
|---|---|---|
| `checkpoint_save` | 存档落好 | `checkpoint_id`、`level`、`manifest_path` |
| `checkpoint_restore` | 新执行线第一条 | `checkpoint_id`、`level`、`parent_branch`、`parent_last_event_uuid`、`to_task` |
| `world_snapshot` | task 开局世界快照落好 | `path` |
| `trace_sealed` | 本局的账封存好 | `checkpoint_id`、`count` |
| `checkpoint_error` | 存档一族某一步失败 | `checkpoint_id`、`stage`、`error` |
| `review_inject` / `review_audit` | 每问一次人（`harness/reviewing.py`） | `form_kind`、`reply` / `verdict`、`note` |

存档一族与问人两本都不进 `node_io` 的活动流（旁路，条数不固定）。

## 七、已知限制

| # | 限制 |
|---|---|
| L2 | 同一 run 的分支不能并行跑（记忆根只有一份） |
| L3 | 恢复会丢原分支存档之后写进记忆的内容 |
| L4 | 回放要求起点存档里有目标线封存的账，且代码版本一致（prompt 逐字比对，改了就报 `ReplayDiverged`） |

## 八、怎么验

- `tests/test_checkpoint_restore.py`：两级存档的形状；两级各恢复一次跑到底；分支套分支；按血缘 `node_io` 全过。
- `tests/test_checkpoint_replay.py`：回放到第 2 局第 2 个 task；沿半路分出来的线再回放；篡改录音报分叉。
- `tests/test_memory_fetch.py`：按键取、自然序。
- 真机：`python -m experiment.real_check.check_checkpoint`（维度 3，见 `docs/spec/experiment/SPEC.md`）。
