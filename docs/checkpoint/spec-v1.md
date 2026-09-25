# spec —— checkpointer

> 流程位置：intent.md → **spec.md** → plan.md → PR → production
> 状态：**已定稿（09-25）** → 下一步 `docs/checkpoint/plan.md`
> 依据：`docs/checkpoint/intent.md`（已定稿）｜ 起草：2026-09-24 ｜ 09-25 按讨论重写（三级存档点、显式存档、由内向外恢复、方案 A 装配）

---

## 一、已定前提

| # | 决定 | 来源 |
|---|---|---|
| D1 | 三级存档点：**run 级 begin、episode 级 begin、task 级 begin**，每个都自动存，`config.py` 一个开关可关 | intent C1 + 09-25 讨论 |
| D2 | 恢复**沿用原 run_id**；分支由 trace `meta` 新增的 `branch` 字段区分；状态、记忆、各类 id 一律不改 | C2（09-24 改定） |
| D3 | 记忆整根快照、含 knowledge_memory，复用 `MemoryToolPort.snapshot_memory` / `restore_memory` | C3 |
| D4 | 图状态由 LangGraph checkpointer（saver）持久化 | C4 |
| D5 | 存档**显式调用**：三个图外入口各在末尾调一次 `checkpointer.save(...)`；不做观察者式的隐式存档 | 09-25 |
| D6 | 恢复**由内向外**：最内层从自己的状态接着跑，每个外层"替 `act` 交差"；外层的 `act` 格不重跑 | 09-24/25 |
| D7 | **装配方案 A**：三张图都在 `build.py` 编译；checkpointer 与各层 `act` 用的是同一批图对象；两个 `act` 模块的模块级图缓存删除 | 09-25 |
| D8 | trace 不回滚、不打作废标记，只追加 | intent |

## 二、术语

| 词 | 意思 |
|---|---|
| **存档点** | 允许存 checkpoint 的位置：三个图外入口的末尾（§三） |
| **checkpoint** | 一次存档的全部产物：世界存档 + 记忆 zip + 清单；外层图状态留在 saver 里，清单只记定位 |
| **清单（manifest）** | 把世界、记忆、本层状态原件、外层图状态定位绑在一起的 JSON；checkpoint 的身份 |
| **分支（branch）** | 一条执行线。未经恢复的是 `main`；每次恢复开一条新分支。一条分支对应 LangGraph 的一个 thread |
| **血缘** | 分支 → 父分支 → checkpoint id → 存档时父分支最后一条事件 uuid |
| **替 `act` 交差** | 在外层图"进 `act` 之前"的状态上，合入 `act` 本该返回的内容，使该层从 `act` 的下一格（`perceive`）接着跑 |

## 三、存档点

三张图都是 5 格同构：`perceive → review_and_judge → plan_<层> → act → <层>_done`，入口都是 `perceive`（run 图入口是 `begin`）。
外层的 `act` 格在节点函数里调用内层的图外入口（`run_episode` / `run_task`），入口先写开局账、装初始状态，再 `invoke` 内层图。

| 存档点 | 调用位置 | 本层 | 外层此刻在哪 |
|---|---|---|---|
| **run 级 begin** | `run_entry.new_run`：`game.reset` 之后、进 run 图之前 | 初始 `RunState` | — |
| **episode 级 begin** | `episode_entry.begin_episode` 末尾（写完 `episode_start` 之后） | 初始 `EpisodeRunState`：任务表为空，**还没拆解** | run 在 `act` 里，最新存档 = run 的"进 `act` 前" |
| **task 级 begin** | `task_entry.begin_task` 末尾（写完 `task_start` 之后） | 初始 `TaskState`：还没按第一个键 | episode 在 `act` 里（task 已由 `plan_episode` 选定），最新存档 = episode 的"进 `act` 前"；run 同上 |

**为什么外层"最新存档"恰好是"进 `act` 前"**：LangGraph 只在节点之间写 checkpoint，外层 `act` 执行期间不会再写，
所以存档那一刻去 saver 查外层的最新一条，查到的就是它进 `act` 之前那一条（前提：`durability="sync"`，见 §5.4）。

**三级存档点的用途**：task 级 = 固定一个 task 反复跑（目标、判据不变）；episode 级 = 同一局重新拆解再跑；run 级 = 整个 run 重跑。
分别对应测评数据集的三种粒度（`docs/eval/intent.md` §五）。

**人在环**：`--review` 下 task 结束会停下等人；审阅结论在下一个 task begin 之前已进状态，信箱不入档（intent C5）。

## 四、落盘布局

```
checkpoints/                                    仓库根，已在 .gitignore
├── langgraph.sqlite                            LangGraph 图状态库（S1）
└── <run_id>/
    └── <checkpoint_id>/
        ├── manifest.json                       清单（§5.1）
        └── world.state                         PyBoy 完整存档
memory/snapshots/<checkpoint_id>.zip            记忆快照（位置由 memory 自己决定，清单记路径）
```

`checkpoint_id`：

| 存档点 | 格式 | 例 |
|---|---|---|
| run 级 | `<run_id>@<branch>` | `r0925@main` |
| episode 级 | `<episode_id>@<branch>` | `r0925-ep3@b2` |
| task 级 | `<episode_id>-<task_id>@<branch>` | `r0925-ep3-t4@main` |

**分支名**：`main`，或 run 内顺序编号 `b1`、`b2`…（09-25 定；原"`<存档名>.r<k>`"方案在分支套分支时会撞名，已弃）。
每个 run 一张分支登记表 `checkpoints/<run_id>/branches.json`：每条分支的父分支、来源 checkpoint_id、完整血缘（由根到父的 `LineageLink` 列表，每项 = 分支、分叉点事件 uuid 与 ts、checkpoint_id）、创建时间。
血缘在登记时就展开成完整列表，读侧不必逐级上溯（实现：`harness/checkpoint/branches.py`）。

## 五、契约

命名按 AGENTS.md 十二：第一跳信封 `From[A]To[B][函数][Req/Resp]` 放发起方；模块接口模型裸名放产出方。

### 5.1 清单：`harness/checkpoint/manifest.py`（实现时放在模块内：清单只在 checkpoint 模块内读写，不跨模块）

| 字段 | 类型 | 说明 |
|---|---|---|
| `checkpoint_id` | str | §四 |
| `level` | `Literal["run", "episode", "task"]` | 存档点级别 |
| `run_id` / `branch` | str | 存档时所在 run 与分支 |
| `episode_id` / `task_id` | `str \| None` | episode 级起有 `episode_id`；task 级起有 `task_id` |
| `run_state` | `RunState \| None` | **run 级**：本层状态原件 |
| `episode_state` | `EpisodeRunState \| None` | **episode 级**：本层状态原件 |
| `task_state` | `TaskState \| None` | **task 级**：本层状态原件 |
| `task_input` | `TaskInput \| None` | **task 级**：`begin_task` 收到的入参（恢复时 `close` 与错误收场要用） |
| `episode_input` | `EpisodeInput \| None` | **episode / task 级**：本局入参 |
| `outer` | `list[GraphRef]` | 外层图"进 `act` 前"的定位，由外到内：run（episode 级、task 级都有）、episode（仅 task 级）。`GraphRef` = `level` + `thread_id` + `checkpoint_ns` + `checkpoint_id` |
| `world_file` | str | `world.state` 相对路径 |
| `memory_archive` | str | `snapshot_memory` 返回的 zip 路径 |
| `last_event_uuid` / `last_event_ts` | str / float | 存档时本执行线（含血缘）最后一条 trace 事件的 uuid 与 ts；run 级存档在开账之前，为空 |
| `lineage` | `list[LineageLink]` | 存档所在执行线的血缘，由根到父（`main` 上为空）；恢复时在末尾接上本存档成为新执行线的血缘 |
| `code` | `CodeStamp` | git commit、工作区是否干净、`state_schema_hash`（三种状态模型 JSON Schema 的哈希） |
| `models` | dict[str, str] | 各模型位置 → 型号 |
| `created_at` | str | ISO 时间 |

**不变式**（`save` 出口 assert）：`level` 与"哪个 `*_state` 非空、`outer` 有几条"一一对应；清单引用的文件都已在盘上。

**为什么本层状态存原件、外层只存定位**：存档那一刻本层图还没 `invoke`，saver 里没有它；外层已经在 saver 里了，存定位即可。

### 5.2 世界：加回存 / 读模拟器状态

- `WorldPort` 加 `save_state() -> bytes`、`load_state(data: bytes) -> None`（裸字段），`PyBoyWorld` 用 `pyboy.save_state` / `load_state` 实现。
- `GameToolPort` 加 `save_state(req) -> resp`、`load_state(req)`；信封 `FromHarnessToGameToolSaveStateReq/Resp`（resp 带 `path`）、
  `FromHarnessToGameToolLoadStateReq`，放 `schemas/harness/communication/`。路径由 harness 给，写文件在 tool 层。
- 顺手订正：`GameToolPort` docstring 称"`world` 层自己仍保留这些能力面"，实际 09-13 已一并删除。

### 5.3 记忆：复用，不改契约

`snapshot_memory(name=checkpoint_id)` / `restore_memory(archive=清单.memory_archive)`。

### 5.4 LangGraph saver

- **一个 saver，挂在 run 图上**：`build.py` 编译 run 图时传 `checkpointer=saver`。episode 图、task 图在节点函数里被 `invoke`，
  预研证实其 checkpoint 自动写进同一个 saver（命名空间 `act:<id>`、`act:<id>|act:<id>`），不单独给 saver。
- **thread = 分支**：`thread_id = f"{run_id}@{branch}"`。原线是 `r0925@main`；每条恢复分支一个新 thread，不在原 thread 上分叉——
  血缘由清单与 trace 记录，不依赖 LangGraph 的分叉链。
- **`durability="sync"`**：三处 `invoke`（`run_entry._invoke`、`run_episode`、`run_task`）都传。默认的 async 下 checkpoint 在后台写，
  存档时去查外层"最新一条"可能还没落库。
- **Pydantic 状态登记**：`allowed_msgpack_modules` 只认逐个的 `(模块路径, 类名)`，按包前缀登记无效（P0 K-d）。装配 saver 时从三种状态模型沿字段类型递归收集全部 Pydantic 模型与枚举，生成精确列表。
- **库文件位置与清理**：待 P3 真机量完增量再定（P0 K-e：假跑一局已约 3.4 MB）。

### 5.5 `Checkpointer` 与装配（方案 A）

新增 `harness/checkpoint/` 包，与 run / episode / task 同级：

| 文件 | 职责 |
|---|---|
| `__init__.py` | 统一出口：`Checkpointer`、`restore_run` |
| `checkpointer.py` | `Checkpointer` 类：持有 saver、三张图、`game` / `memory` / `trace` 三个 tool；`save(...)` |
| `restore.py` | 图外入口 `restore_run`（§6.2） |
| `manifest_io.py` | 清单读写（临时文件 + 原子改名）、版本核对 |
| `errors.py` | 模块错误根 `CheckpointError`；`CheckpointNotFound` / `CheckpointIncompatible` / `CheckpointCorrupt` |

`Checkpointer.save` 的签名（示意，plan 阶段定稿）：

```python
def save(self, *, level: Literal["run", "episode", "task"], run_id: str, branch: str,
         state: RunState | EpisodeRunState | TaskState,
         episode_input: EpisodeInput | None = None, task_input: TaskInput | None = None) -> str: ...
```

**装配（D7）**：

| 对象 | 由谁造 | 交给谁 |
|---|---|---|
| saver | `build.py` | run 图编译、`Checkpointer` |
| task 图 | `build.py`：`compile_task_graph()` | `EpisodeRuntime.task_graph`、`Checkpointer` |
| episode 图 | `build.py`：`compile_episode_graph()` | `RunRuntime.episode_graph`、`Checkpointer` |
| run 图 | `build.py`：`compile_run_graph(checkpointer=saver)` | `RunHarness`、`Checkpointer` |
| `Checkpointer` | `build.py` | `RunRuntime` / `EpisodeRuntime` / `TaskRuntime` 的 `checkpointer` 字段（**同一实例**，同 `trace` / `memory` 的现行做法） |

连带：删除 `run/act` 的 `_episode_graph` / `episode_graph()` 与 `episode/act` 的 `_task_graph` / `task_graph()`，
两个 `act` 改为 `runtime.context.episode_graph` / `runtime.context.task_graph`；`RunHarness._compile()` 改为收 build 编译好的图。
（模块级全局缓存本身违反"禁止模块级单例、组装只在唯一装配点"，借此修正。）
`Checkpointer` 不另写 Protocol：实现方在系统内、无第二实现（ai-coding-paradigm"接口三问"）。

### 5.6 从 `act` 格提出的共用函数

"替 `act` 交差"要逐字段复现 `act` 的返回与异常收场。为避免两份实现悄悄分叉，从两个 `act` 各提出两块，`act` 自己也改调它们：

| 函数 | 来自 | 做什么 |
|---|---|---|
| `run.act.dispatch` | 已是纯函数 | 选目标、盖 RUNNING、拼 `EpisodeInput`，返回 `{"goals", "episode_input", "step"}` |
| `run.act.settle_episode_error(deps, run_id, episode_input, exc, *, source)` | 现 `_episode_error` | 补空章 → 记 `episode_error` → `AgentError` 兜成 `ERROR`，其余原样抛 |
| `episode.act.dispatch_task(state)` | 现 `act` 步骤 1 | 选第一条 PENDING、盖 RUNNING、拼 `TaskInput`，返回 `{"tasks", "task_input"}` |
| `episode.act.settle_task_error(deps, task_input, exc, *, source)` | 现 `_task_error` | 记 `task_error` → `AgentError` 兜成 `ERROR`，其余原样抛 |

`source` 参数区分是 `act` 接住的还是恢复路径接住的（"谁接住谁记账"）。

## 六、流程

### 6.1 保存（三级同一流程）

1. `game.save_state(path=checkpoints/<run_id>/<cid>/world.state)`；
2. `memory.snapshot_memory(name=<cid>)`；
3. 按级别查外层定位：episode 级查 run thread 的根命名空间最新一条；task 级再查 episode 命名空间最新一条；
   assert 每条的 `next == ("act",)`（查到的不是"进 `act` 前"说明时序假设被破坏，是 bug）；
4. 组装清单、assert 不变式、原子写 `manifest.json`；
5. 记账 `checkpoint_save`。

任一步失败：不写清单，记 `checkpoint_error`，**run 继续跑**（S4）。

### 6.2 恢复：由内向外

`restore_run(manifest_path, build_branch) -> run 级四元组`（`build_branch(分支名, 血缘) -> RunRuntime`，真机包一层 `build_real`）：

**公共前置**
1. 读清单，核对 `state_schema_hash`（不一致抛 `CheckpointIncompatible`；git commit 不同只告警）；
2. 定新分支名，`build` 一套 runtime（同 run_id、新 branch；`TraceTool.build(run_id=…, branch=…)`；新 thread）；
3. `memory.restore_memory`、`game.load_state`；
4. 记账 `checkpoint_restore`（新分支第一条事件，正文带血缘）。

**按级别续跑**

| 级别 | 最内层 | 交差 |
|---|---|---|
| run | `invoke(清单.run_state, 新 thread)`，从 `begin` 起跑 | — |
| episode | `episode_graph.invoke(清单.episode_state)`，入口 `perceive`；`close` 取 `EpisodeOutput`；异常 → `settle_episode_error(source="checkpoint.restore")` | 替 run 的 `act` 交差 |
| task | `task_graph.invoke(清单.task_state)`，入口 `perceive`；`close` 取 `TaskOutput`；异常 → `settle_task_error(source="checkpoint.restore")` | 先替 episode 的 `act` 交差，再替 run 的 `act` 交差 |

所有最内层续跑都**不调 `begin_*` 入口**（开局账已在父分支里，不重复记）。

**替 episode 的 `act` 交差**（仅 task 级）：
```
pre  = EpisodeRunState(saver 中 outer[episode] 的值)          # 进 act 前
back = {**dispatch_task(pre) 的 tasks, "pending_task": TaskOutput, "step": pre.step + 1}
episode_graph.invoke(pre.model_copy(update=back))             # 入口 perceive = act 的下一格，跑完这一局
→ close → EpisodeOutput（异常 → settle_episode_error）
```
episode 图不挂在 saver 的顶层，没法对它 `update_state`；但它的入口正是 `act` 的下一格，所以"合入 `act` 的返回后从入口重新 `invoke`"等价。

**替 run 的 `act` 交差**（episode 级、task 级）：
```
pre  = saver 中 outer[run] 的 checkpoint（next == ("act",)）
写入新 thread：update_state(新 thread, {**pre 的值, **dispatch(pre), "pending_episode": EpisodeOutput}, as_node="act")
run_graph.invoke(None, 新 thread, durability="sync")          # next == ("perceive",)，act 不执行
```

**一致性 assert**：`dispatch_task(pre)` 算出的 `task_input` 与清单里的 `task_input` 相等；`dispatch(pre)` 算出的 `episode_id` 与清单相等。
不等说明"纯函数重算"的前提被破坏，是 bug。

## 七、trace 变更（按规范须与你商定）

**封套 `meta` 由五件变六件**：新增 `branch`（未经恢复为 `"main"`）。与 `run_id` 一样由落盘层盖章（`TraceTool.build(run_id=…, branch=…)` 构造期持有），harness 组装 req 时不填。

**`read_events` 按分支血缘读**：`TraceTool` 持有本分支血缘；`read_events` 按登记表逐级上溯拼接：`main` 截至第一个分叉点 + 各中间分支截至下一个分叉点 + 本分支全部事件。
现有唯一依赖跨步读账的调用方是 `_task_error` 数本 task 已按键数——恢复后同 run_id 下会有多条分支的同名 task，不按分支读会数错。

新增三个 `TraceKind`：

| kind | 何时 | 正文 |
|---|---|---|
| `checkpoint_save` | 每次成功存档（`meta.source` = 调用它的入口） | `checkpoint_id`、`level`、`manifest_path` |
| `checkpoint_restore` | 每次恢复，新分支第一条事件 | `checkpoint_id`、`level`、`parent_branch`、`parent_last_event_uuid` |
| `checkpoint_error` | 存档失败 | `checkpoint_id`、`stage`、`error` |

连带：`node_io.py` 的 `META_KEYS` 加 `branch`；后继表、`CONTRACTS`、`KNOWN_SOURCES` 登记新 kind 与新 source（`checkpoint.restore`）；
切流前先按血缘把分支拼完整——拼接后恢复分支的流里开局账来自父分支，拓扑判据不需要特例。测评按 `(run_id, branch)` 分组。

## 八、LangGraph 预研结论（2026-09-24/25）

环境：langgraph 1.2.11 + langgraph-checkpoint 4.2.0，`InMemorySaver`，最小复现脚本（非项目代码）。

| # | 问题 | 结论 |
|---|---|---|
| K1 | 节点函数里 `invoke` 的内层图，状态能否进同一个 saver | **能**，三层嵌套都进同一个 saver，命名空间逐层加深；内层拿到的是自己的 context |
| K2 | 在外层"进 `act` 前"的状态上以 `act` 的名义写入 | **能**：`update_state(…, as_node="act")` 后 `next == ("perceive",)`，`invoke(None)` 的执行序列里没有 `act`；写进新 thread 也可以 |
| K3 | 内层续跑 | 不需要 LangGraph 的子图续跑：内层图入口都是 `perceive`，即 `act` 的下一格，用状态原件重新 `invoke` 即可 |
| K4 | 存档时查外层最新 checkpoint 是否就是"进 `act` 前" | 执行期间内层 `put` 带着外层当时的 checkpoint id，与外层 `next == ("act",)` 那条一致；**须 `durability="sync"`** |
| — | 把内层注册成真子图 | **不做**：子图节点会拿到父图的 context，且各层状态形状不同 |

仍需在真实代码上核实（plan 第一步）：两个 `dispatch` 重算结果与当时一致；恢复不产生多余的开局账；`TaskRuntime` 帧槽在 task begin 时是否需要入档
（task begin 时该 task 的首键还没取帧，预期不需要）。
**若核实结果是需要**：帧槽从 `TaskRuntime` 移进 `TaskState`（09-25 定）——它本就是 `(episode_id, step, base64 PNG)`，能 JSON 化，按"能 JSON 化且图上要读 → 进 state"的判据也该在 state；随之由 saver 自动持久化，不另做入档。代价：task 图每个 super-step 的 checkpoint 多带两张帧的 base64，sqlite 库增长加快，plan 阶段量一次单局增量。

## 九、保真核对

`experiment/real_check/check_checkpoint.py`（与其余核对脚本同形，独立进程）：

1. 真机跑一个短 run，至少产生 1 个 run 级、1 个 episode 级、2 个 task 级存档；
2. 三个级别各挑一个**只回档不开跑**（`open_branch`），与原 checkpoint 比对：世界再存一次逐字节相同；记忆再拍快照，zip 成员与逐文件哈希相同；
   外层图"进 `act` 前"的状态从 saver 读回，重算的 `episode_input` / `task_input` 与清单相同（09-25 实现时改：`save` 要在图的执行上下文里取外层定位，回档后调不了）；
3. 同一 checkpoint 连续恢复 3 次，三次起点读数相同；
4. 恢复后跑完，新分支第一条事件是 `checkpoint_restore`；按血缘拼接后 `node_io` 全部判据通过；原分支的 trace 文件一字节未变；
5. 改坏 `state_schema_hash`，恢复被拒并抛 `CheckpointIncompatible`。

## 十、已确认（09-25）

| 编号 | 问题 | 结论 |
|---|---|---|
| S1 | saver 实现 | **sqlite**：`pyproject.toml` 新增 `langgraph-checkpoint-sqlite` |
| S2 | trace 变更 | **按 §七**：`meta` 加 `branch`、`read_events` 按血缘拼接读、新增 `checkpoint_save` / `checkpoint_restore` / `checkpoint_error` / `checkpoint_skipped` |
| S3 | `checkpoint_id` 与分支名格式 | 按 §四（分支 `main` / `b<n>` + 登记表） |
| S4 | 存档失败时 run 继续 | 继续：不写清单，记 `checkpoint_error` |
| S5 | 版本核对 | git commit 不同只告警；`state_schema_hash` 不同拒绝加载 |
| S6 | 旧 trace 没有 `branch` 字段 | **不做兼容：`branch` 落地时删除旧 trace 历史**（`tracelog/` 现有事件），之后盘上每条事件都带 `branch`；读取侧缺 `branch` 视为损坏，不补缺省值。删除动作放进 plan，执行前再与你确认一次 |
| S7 | LangGraph thread | 按分支分：`thread_id = <run_id>@<branch>` |
| S8 | 已知限制 | 按 §十一 L1–L3 |

## 十一、已知限制（09-25 定）

| # | 限制 | 原因 | 以后怎么解 |
|---|---|---|---|
| L1 | **续跑段不存档**：从 episode / task 级存档恢复后，被打断的那一局（及那个 task）在图外续跑的这一段里，`save()` 直接跳过并记 `checkpoint_skipped`；run 图接手后恢复正常 | 续跑段的内层图不挂 saver，新分支 thread 里也还没有外层"进 `act` 前"的那一条，查外层定位会查不到或查到父分支 | 需要续跑段样本时：恢复开始先把外层"进 `act` 前"状态复制进新 thread，续跑的内层图挂 saver 独立跑，`save()` 在续跑段改用复制件 |
| L2 | **分支不能并行跑**：同一个 run 同一时刻只有一条分支在跑 | 记忆根只有一份，恢复会整根覆盖 | 测评需要并行时，每条分支各用独立的记忆根 |
| L3 | 恢复后，原分支存档之后写进记忆的内容从盘上消失 | 同 L2 | 从原分支更晚的存档再恢复即可回到那条线（存档之后、中断之前的记忆找不回） |

`Checkpointer` 持有"正在续跑"标志：`restore_run` 进入续跑段时置位、交差完成后清除；标志置位时 `save()` 只记 `checkpoint_skipped` 不存档。
§七 的新 `TraceKind` 相应再加一个 `checkpoint_skipped`（正文：`level`、`reason="resume_stretch"`）。

## 十二、不在本 spec

task 内部（键级）恢复；自动清理旧存档；跨版本迁移；测评数据集如何引用 checkpoint（归 `docs/eval/`）。
