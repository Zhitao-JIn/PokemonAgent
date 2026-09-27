# intent —— checkpointer：以 task 为最小单元的存档与恢复

> 流程位置：**intent.md** → spec.md → plan.md → PR → production
> 状态：草稿（2026-09-26）
> 下游：`docs/eval/intent.md`（测评数据集的样本就是 checkpoint）、`docs/wikiskill/intent.md`（验证集）
> 对应 ROADMAP：H9 状态恢复、F5 存档片段回归集

---

## 一、一句话意图

**在任意一个 task 边界，把"世界 + 三层图的状态 + 记忆"整份存下来；之后能直接回到存下的那一刻，在图内接着跑。
trace 不回滚、不打作废标记，也不参与恢复：它只追加账，分支关系从账本自己推出来。**

## 二、为什么做

1. **测评数据集需要它。** 现有 `experiment/experiment_states/*.state` 只有模拟器状态，没有图状态和记忆，
   只能从"空记忆 + 开局"起跑。要以 task / episode / run 为单位做样本（"第 3 局第 5 个 task、带着前面积累的记忆"），
   样本本身就得是一个完整 checkpoint。
2. **失败片段可复现。** 真机跑出的一个失败 task，可以从它开始前那一刻反复重跑。这也是 ROADMAP F5 的前提。
3. **WikiSkill 的验证集**从同一批 checkpoint 里切。
4. **Agent 工程清单第 6 项**：agent 必须能在任意 step 后持久化并恢复——"从玩具到生产线的分水岭，不可协商"。

## 三、设计原则

| 原则 | 含义 |
|---|---|
| 不作废，只整体还原 | 记忆用整根快照（`snapshot` / `restore`，以 zip 为准，多出来的直接删），不逐条打作废标记、不建归档目录 |
| trace 只追加 | 历史账一条不动；恢复只追加一笔恢复账，分支靠账上的 `branch` 与 `checkpoint_id` 区分 |
| 各模块不懂"恢复" | memory 只会拍照 / 还原，trace 只会追加，世界只会存 / 读档；"恢复"这件事只住在 checkpointer 与各层 `act` 里 |
| 图内恢复，不回放 | 用 LangGraph 原生的 `update_state(as_node=…)` + `invoke(None)` 把每层图放回"进 `act` 前"，已完成的 task 不重跑、不重演 |
| checkpointer 对 trace 只写不读 | 存档与恢复都不依赖读 trace；trace 只是它记账的地方 |

## 四、一个 checkpoint 里有什么

| 组成 | 内容 | 怎么存 |
|---|---|---|
| 世界 | PyBoy 模拟器完整状态 | 文件，放在该存档目录里 |
| run 层状态 | `RunState`：run 图进 `act` 前那一刻 | saver 地址 `run_ref`（run 级存档存 `RunState` 原件——此时还没进图） |
| episode 层状态 | `EpisodeRunState`：episode 图进 `act`、派该 task 之前那一刻 | saver 地址 `episode_ref`（仅 task 级） |
| 记忆 | 整个记忆根的 zip（各族一起） | `snapshot_memory`，清单引用其路径 |
| 元信息 | `checkpoint_id`、级别、run_id、所在执行线、episode_id / task_id、代码版本与状态结构版本、各位置模型档、创建时间 | 清单 |

**不在 checkpoint 里的**：trace（它是账本，不是状态）；模型的随机性（同一 checkpoint 跑两次结果可以不同，这正是测评要重复 k 次的原因）；
进程内缓存（向量索引等由 `restore` 重读重建）；task 图的状态（task 级存档点就是它的开局，由 `begin_task` 重新装配）。

## 五、语义

**保存**：三级存档点各在自己那一层的 begin，一次调用把 §四 的组成一起落盘，一个 checkpoint 一个目录，记一笔 `checkpoint_save`。

**恢复到 task k**：
1. 世界从该存档的世界文件读档，记忆从 zip 还原；
2. run 图开新 thread `<run_id>@<新branch>`，按 `run_ref` 读出 `RunState`、写入新 `branch`，`update_state(as_node="plan_run")` → `invoke(None)`；
3. run 的 `act` 处于恢复模式：`dispatch` 照常；不走 `begin_episode` + 全新 `invoke`，而是按 `episode_ref` 读出 `EpisodeRunState`，
   在 `get_config()` 上 `update_state(as_node="plan_episode")` → `invoke(None)`；
4. episode 的 `act` 与 `begin_task` 照常执行：`begin_task` 为新线写 `task_start`，并存下新线自己的 task 级存档；
5. 新线第一笔账是 `checkpoint_restore`（meta 带 `checkpoint_id`）；之后的账都属于新线，父线的账原封不动。

episode 级恢复只做第 1、2 步（run 的 `act` 照常派这一局）；run 级从开局跑。

**可见历史**：一条线能看到的账 = 自己的全部 + 血缘上每个祖先在分叉点及之前的账。同一个 task 在父线与新线各有一份账，
读侧按血缘截断筛选，不按业务键去重。

**保真**：恢复后的状态 = 存下的状态（模拟器内存、两层图状态、记忆文件清单与内容逐项相同）。恢复后从目标 task 开局起是全新执行，不承诺结果一样。

**版本**：checkpoint 带着生成它的代码版本与状态结构版本；结构不兼容时**拒绝加载并报出原因**，不静默尝试。

## 六、范围

**做**
- 三级存档（run / episode / task begin）与对应的图内恢复；
- 分叉点、血缘、分支图全部从 trace 推导；
- 保真核对（§五），作为验收脚本；
- 列出 / 查看已有 checkpoint 的最小入口；
- 删除为回放而设的机制：`tools/replay/`（五个磁带件与 `ReplayDiverged`）、`seal_episode` 与 `trace_sealed`、`world_snapshot`、`branches.py` / `branches.json`、
  对象读 `refs` 唯一键、记忆按自然键取的读口、查询的 `order_by` 规矩与 act 记忆的 `task_id`、"所有记忆读都记读账"。问人两本账（`review_inject` / `review_audit`）保留：它们记着人是否真答、等了多久、审的是什么，是人在环的审计依据。

**不做**
- task 内部（键级）恢复；
- 自动清理旧 checkpoint 的策略（先手动）；
- 跨代码版本的迁移；
- 与 E1（subagent 编排）的对接——E1 落地时它的 subagent 边界若与 task 边界不同，再议；
- 恢复后保证"结果一样"——模型是随机的，不承诺。

## 七、已拍板

| 编号 | 问题 | 结论 |
|---|---|---|
| C1 | 什么时候存 | **三级完整存档，都在各层 begin**：run 级在 `run_entry.new_run`（reset 之后、进图之前）；episode 级在 run 的 `act` 开头；task 级在 `begin_task`。`config.py` 一个开关可关；旧 checkpoint 先手动清理 |
| C2 | 分支的身份 | **沿用原 run_id**，trace 封套 `meta` 的 `branch` 区分执行线（换 run_id 会让恢复后的 agent 查不到存档前的记忆）；run 图一条执行线一个 thread：`<run_id>@<branch>` |
| C3 | knowledge_memory 随不随快照回滚 | **一起回滚**：整根 `snapshot` / `restore`，不改 memory 契约；存档后手改的知识靠 git 找回 |
| C4 | 实现路线 | **用 LangGraph 自带的 checkpointer**（sqlite saver）持久化图状态；只有 run 图编译时带 saver；episode、task 图不带，运行时继承父图 config 里的同一个 saver，嵌套状态照样落盘；恢复时读 episode 状态直接调 saver 的 `get_tuple`。世界与记忆由我们在同一存档点另存，清单把三者绑成一个 checkpoint |
| C5 | 人在环的状态 | 存档点在上一个 task 的审阅结束之后，信箱不入档 |
| C6 | 存放位置 | 仓库根 `checkpoints/`（gitignore）；记忆 zip 由 memory 自己放在 `memory/snapshots/`，清单引用其路径 |
| C7 | 清单存状态还是地址 | **存 saver 地址**。task 级存档在 `begin_task` 里从执行上下文的 `checkpoint_map` 取两条：`""` → `run_ref`，episode 图的命名空间 → `episode_ref`；`run_ref` 核 `next == ("act",)`，`episode_ref` 核父指针等于 `run_ref` |
| C8 | task 级存档存几次 | **一次**：`begin_task` 里一次 `save(level="task")`，两个地址当场取，世界与记忆当场拍。三级都记 `checkpoint_save`，不设单独的世界快照账 |
| C9 | 恢复标记放哪 | 放 runtime context，run 的 `act` 用一次即清，不进图状态 |
| C10 | 记忆与分支 | **不加分支概念、不加回退接口**：每个存档点一份 zip。父线最后一个存档点之后写进活库的那段尾巴，恢复分支时会被抹掉——它不对应任何存档点，接受 |
| C11 | checkpointer 与 trace | **只写不读**：存档不读分叉点，结束一局不封存账 |
| C12 | 分叉点、血缘与分支图 | `checkpoint_save`、`checkpoint_restore` 的 **meta** 带 `checkpoint_id`（放 meta 以便 `read_events` 筛）。分叉点 = 该 `checkpoint_save` 本身（含它）；父线 = 该 `checkpoint_save` 的 `branch`，不另记 `parent`；新线名随机：`b-<6 位 hex>`（名字要在装配新线之前定，不读账）。TraceTool 从自己的账本算血缘，装配点不递 `lineage` |
| C13 | `checkpoint_id` | `<episode_id 或 run_id>@<branch>-<8 位随机 hex>`（`uuid4`），不靠存档目录是否存在去重。save 生成一次写进清单与 `checkpoint_save`，restore 只读清单；恢复时断言本 run 里该 id 的 `checkpoint_save` **恰好一条**，否则拒绝 |
| C14 | `query_episode_summaries` 的排序 | 删掉 `order_by` 后，由 `query_episode_summaries` 内部固定按 `episode_id` 自然序排（`ep2 < ep10`），不开参数；调用方不再各自排序 |

## 八、开工前提（探测）

§五第 3 步是"在正在运行的父节点里对嵌套子图 `update_state`，再用同一个 config `invoke(None)`"，这条路径未验证。先用 fake run 做最小用例，断言：
1. 写入后 `episode_graph.get_state(cfg).next == ("act",)`；
2. `invoke(None)` 第一个执行的就是 `act`，`perceive` / `plan_episode` 没有重跑（数调用次数）；
3. episode 图跑完，run 的 `act` 正常拿到 `EpisodeOutput`，run 图照常回到 `perceive`。

三条都过，本 intent 成立。

## 九、成功的样子（intent 层验收）

1. 真机跑一个 run，在任意 task 边界存档；
2. 从该 checkpoint 直接恢复到该 task，保真核对全部通过；
3. 恢复后接着跑完，trace 里能看到恢复账；分支图能仅从 trace 画出，每条线按血缘拼读后完整；
4. 同一个 checkpoint 连续恢复 k 次，每次起点完全相同（为测评重复运行做准备）；
5. 版本不兼容的 checkpoint 被拒绝加载，报错说明原因。

## 十、参考

- 仓库内：`pokemon_agent/memory/ports.py`（`snapshot` / `restore` 契约）、`pokemon_agent/tools/interface/ports.py`（`snapshot_memory` / `restore_memory`）、
  `pokemon_agent/harness/checkpoint/`（`checkpointer.py` 的 `_run_ref`、`restore.py`）、`pokemon_agent/tools/trace/__init__.py`（按血缘拼读）、
  `pokemon_agent/harness/run/run_state.py`、`pokemon_agent/harness/episode/episode_state.py`、`docs/ROADMAP.md` H9 / F5
- LangGraph：`pregel/_algo.py`（子图命名空间 = `<ns>:<task_id>`）、`pregel/main.py`（`update_state` 从 config 取 checkpointer）
