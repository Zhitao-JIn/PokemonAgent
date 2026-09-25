# intent —— checkpointer：以 task 为最小单元的存档与恢复

> 流程位置：**intent.md** → spec.md → plan.md → PR → production
> 状态：**已定稿**（2026-09-24）；**09-25 修订**（见 §十）→ `docs/checkpoint/spec.md` v2
> 起草：2026-09-24 ｜ 下游：`docs/eval/intent.md`（测评数据集的样本就是 checkpoint）、`docs/wikiskill/intent.md`（验证集）
> 对应 ROADMAP：H9 状态恢复（现写"E1 之后以 subagent 边界重做"，本 intent 把它提前到 task 边界，需同步改 H9）

---

## 一、一句话意图

**在任意一个 task 边界，把"世界 + 三层图的状态 + 记忆"整份存下来；之后能回到存下的那一刻接着跑。
trace 不回滚、不打作废标记，只追加一笔"从 checkpoint X 恢复"的账，新分支记下它从哪来。**

## 二、为什么现在做

1. **测评数据集需要它。** 现有 `experiment/experiment_states/*.state` 只有模拟器状态，没有图状态和记忆，
   只能从"空记忆 + 开局"起跑。要以 task / episode / run 为单位做样本（"第 3 局第 5 个 task、带着前面积累的记忆"），
   样本本身就得是一个完整 checkpoint。
2. **失败片段可复现。** 真机跑出的一个失败 task，今天只能看 trace；有了 checkpoint，可以从它开始前那一刻反复重跑。
   这也是 ROADMAP F5（存档片段回归集）的前提。
3. **WikiSkill 的验证集**从同一批 checkpoint 里切。
4. **Agent 工程清单第 6 项**：agent 必须能在任意 step 后持久化并恢复——"从玩具到生产线的分水岭，不可协商"。

## 三、上一次为什么失败，这次怎么避开

09-13 那版 checkpoint 被整体删除（CHANGELOG 57："先全删掉，我感觉写的不行"）。当时的恢复链靠**作废标记**：
memory 的 `void_memory_after` 把之后的记录搬进 `voided-*` 目录，trace 的 `void_after` 给之后的事件打 `valid=false`。
这让"盘上现在是什么"取决于一堆标记，而且每个模块都得懂恢复。

这次的两条不同：

| | 上次 | 这次 |
|---|---|---|
| 记忆 | 逐条作废 + 归档目录 | **整根快照**：`MemoryStorePort.snapshot(name)` / `restore(archive)`（0916 已有），以 zip 为准，多出来的直接删 |
| trace | `void_after` 打 `valid=false` | **不动历史**，只追加一笔恢复账；分支靠血缘记录区分 |

结果是：memory 只需要会"拍照 / 还原"，trace 只需要会"追加"，谁都不需要理解"恢复"这件事。

## 四、一个 checkpoint 里有什么

| 组成 | 内容 | 现状 |
|---|---|---|
| 世界 | PyBoy 模拟器完整状态 | 0913 已从 `WorldPort` 删除 `save_state` / `load_state_bytes`，需要重新加回（`reset()` 里读起点存档的那条还在） |
| run 层状态 | `RunState`（目标表、已派局数、失败连击、已完成局的输出…） | Pydantic 模型，可序列化；尚无存取入口 |
| episode 层状态 | `EpisodeRunState`（任务表、已完成 task 的输出、失败连击、计数…） | 同上 |
| 记忆 | 整个记忆根的 zip（五族一起） | **已有**：`snapshot` / `restore` |
| 元信息 | run_id、episode_id、下一个 task 在任务表里的位置、step 计数、git commit、工作区是否干净、各位置模型档、`config.py` 旋钮、父 checkpoint、存档时 trace 的最后一条事件 uuid、创建时间 | 无 |

**不在 checkpoint 里的**：trace（它是账本，不是状态）；模型的随机性（同一 checkpoint 跑两次结果可以不同，这正是测评要重复 k 次的原因）；
进程内缓存（向量索引等由 `restore` 重读重建）。

**存档点的精确位置**（09-25 定）：三级各在自己的图外入口末尾存——run 级 begin、episode 级 begin、task 级 begin；外层此刻都停在各自"进 `act` 前"。详见 `spec.md` §三。

## 五、语义

**保存**：在 task 边界把 §四 的组成一起落盘，一个 checkpoint 一个目录（或一个包），带唯一 id。
episode 边界与 run 开始是 task 边界的特例，不单独设计。

**恢复**：
1. 世界、run 状态、episode 状态、记忆都回到保存那一刻；
2. trace 追加一笔"从 checkpoint X 恢复"的账，写明 X 的 id、X 所在分支、存档时的最后一条事件 uuid；
3. 之后的账属于**新分支**，能从 trace 追溯到它的来源；原分支的账原封不动；
4. 从恢复点接着跑：episode 派发下一个 task，一切照常。

**保真**：保存 → 恢复 → 立即再保存，两个 checkpoint 除元信息外逐项相同（模拟器内存、两层状态、记忆文件清单与内容）。

**版本**：checkpoint 带着生成它的代码版本与状态结构版本；结构不兼容时**拒绝加载并报出原因**，不静默尝试。

## 六、范围

**做**
- task 边界的保存与恢复（含 episode 边界、run 开始这两个特例）；
- `WorldPort` 加回存 / 读模拟器完整状态；
- 恢复账与分支血缘；
- 保真核对（§五），作为验收脚本；
- 列出 / 查看已有 checkpoint 的最小入口。

**不做**
- task 内部（键级）恢复；
- 自动清理旧 checkpoint 的策略（先手动）；
- 跨代码版本的迁移；
- 与 E1（subagent 编排）的对接——E1 落地时它的 subagent 边界若与 task 边界不同，再议；
- 恢复后保证"结果一样"——模型是随机的，不承诺。

## 七、已拍板（2026-09-24）

| 编号 | 问题 | 结论 |
|---|---|---|
| C1 | 什么时候存 | **（09-25 改，见 §十）** ~~三级 begin 自动存~~：run 级 begin、episode 级 begin（还没拆解）、task 级 begin（还没按键），`config.py` 一个开关可关；旧 checkpoint 先手动清理（09-25 细化，详见 spec §三） |
| C2 | 分支的身份 | **沿用原 run_id**，trace 封套 `meta` 新增 `branch` 字段区分分支（09-24 由"新 run_id"改定：id 与记忆隔离键耦合，换 run_id 会让恢复后的 agent 查不到存档前的记忆）；血缘写进恢复账与清单 |
| C3 | knowledge_memory 随不随快照回滚 | **一起回滚**：沿用现有整根 `snapshot` / `restore`，不改 memory 契约；存档后手改的知识靠 git 找回 |
| C4 | 实现路线 | **用 LangGraph 自带的 checkpointer** 持久化图状态；世界与记忆由我们在同一存档点另存，元信息把三者绑成一个 checkpoint |
| C5 | 人在环的状态 | spec 给默认：存档点放在该 task 的审阅结束之后，信箱不入档 |
| C6 | 存放位置 | spec 给默认：仓库根 `checkpoints/`（gitignore），记忆 zip 仍由 memory 自己放在 `memory/snapshots/`，元信息引用其名字 |

## 八、成功的样子（intent 层验收）

1. 真机跑一个 run，在任意一个 task 边界存档；
2. 从该 checkpoint 恢复，保真核对全部通过；
3. 恢复后接着跑完，trace 里能看到恢复账，新旧两个分支都能被完整重建；
4. 同一个 checkpoint 连续恢复 k 次，每次起点完全相同（为测评重复运行做准备）；
5. 版本不兼容的 checkpoint 被拒绝加载，报错说明原因。

## 九、参考

- 仓库内：`pokemon_agent/memory/ports.py`（`snapshot` / `restore` 契约）、`pokemon_agent/memory/store.py`、
  `pokemon_agent/harness/run/run_state.py`、`pokemon_agent/harness/episode/episode_state.py`、
  `CHANGELOG.md` 2026-09-13（57）、`docs/ROADMAP.md` H9 / F5
- `.workbuddy/backup/checkpoint-removal-20260913-144948.tar.gz`：上一版实现的快照，可对照其失败点

## 十、09-25 修订：两级存档 + 回放到 task

v1（三级 begin 存档）实现后发现：从 episode / task 级存档恢复时，被打断的那一局要在图外跑完再"替 `act` 交差"，
这一段存不了档；要补就得让续跑图单独挂 saver、另开 thread。讨论后改为：

| 编号 | 问题 | 结论 |
|---|---|---|
| C1′ | 什么时候存 | 完整存档两级：**run 级 begin**、**episode 级 = run 的 `act` 开头**（都不嵌套在任何 `act` 里）；每个 task begin 只存一份世界快照 |
| C7 | 怎么到达某个 task | **回放**：从所属 episode 的存档恢复，按 trace 把前面的 task 原样喂回去（模型输出、观测、人的回话都取自账），到该 task 开局时读它的世界快照、切回真件 |
| C8 | 回放靠什么 | **只靠 trace 与存档**，不依赖随机数或"同样输入得同样输出"；记忆读按账上 `refs` 直接取；trace 字段不够就补 |
| C9 | 回放段记不记账 | 不记；新线从该 task 开局起记账，分叉点是父线里该 task 的 `task_start` 的前一条 |
| C10 | trace 要补什么 | 四处：新账 `review_inject` / `review_audit`（每次插话、每次审各记一条回话）；`read_object_memory` 的 `refs` 改为唯一键 `(episode_id, step, place.key)`；新账 `world_snapshot`（task 世界快照落点）；删 `checkpoint_skipped` |
| C11 | 回放怎么判"没走偏" | 回放段每一笔本该落的账都与父线逐条比 `kind` 与正文（去掉 uuid / ts / 耗时这类每次都变的字段），并逐字比每次模型调用的 prompt；对不上即"回放分叉"，恢复中止 |
| C12 | 记忆按 `refs` 取靠什么 | memory 加通用的"按自然键取"读口（act `(ep, step)`、task `(ep, task_id)`、episode `episode_id`、object `(ep, step, place)`、knowledge `source`），不含回放概念 |
| C13 | v1 已写的代码 | 删：图外续跑、替 `act` 交差、`resuming`、task 级完整存档；留：分支与血缘、sqlite saver、世界存读、清单骨架 |
| C14 | 回放的账放哪才安全 | **每局结束时封存本局的账**：把"从这份 episode 存档到这一局结束"这一段（按本执行线血缘）复制进该存档的 `trace@<执行线>/`（从半路回放出来、这一局没有自己存档的执行线，封进这一局的起点存档）；run 中途出错时由 `run_error` 的收场把已写出的部分封存。每份 episode 存档自带回放所需的账，不再依赖 `tracelog/` 在盘；每条账只多复制一次 |
| C15 | task 世界快照怎么分执行线 | 按执行线分开存：`checkpoints/<run_id>/worlds/<episode_id>/<task_id>@<branch>.state`，路径记在 `world_snapshot` 账上，回放按账取 |
| C16 | 回放从哪起、用谁的账 | 起点 = 目标 task 所在局在**血缘上最近的那份 episode 存档**（从半路分出来的线，这一局可能用的是父线的存档）；磁带 = 目标线按血缘拼好的账。回放段内的存档点一律不存（那一份与父线已有的相同） |
| C17 | 记忆查询的规矩 | **筛选与排序一律放进查询条件**：查询带 `conditions`（等值筛）与 `order_by`（按已有元数据的**自然序**，数字部分按数值比），harness 不再在查完之后二次过滤或排序。act 记忆的元数据加 `task_id`（`retrieve_act_memories` 改为按 task 查）；`read_plan_context` 改为 `order_by="episode_id"`（`<run_id>-ep<n>` 自然序即执行序，顺带修掉现在字典序到第 10 局就错的问题） |
| C18 | 哪些读要记账 | **所有记忆读都记读账、回放时都按 refs 取**；`EpisodeMemory` 照旧从记忆读（同构），`leave_chapter`"先查再写"的那次查询补 `read_episode_memory` 账 |

回放要求父线的 trace 完整在盘、代码版本与父线一致（代码改了 prompt 就对不上，报回放分叉）。

§五"恢复"第 4 条相应变为：run 级从开局接着跑；episode 级从 run 的 `act` 重新派这一局；task 级先回放再接着跑。
§八验收第 1 条改为"在任意 episode 边界存档、回放到任意 task"。
