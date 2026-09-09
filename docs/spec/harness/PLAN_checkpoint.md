# PLAN —— Checkpoint / Resume 设计方案（v4，2026-09-07）

> 需求（用户原话）：粒度就是 run / episode / step 三级，可以完整恢复到一样的境地。
> v2 变更：吸收用户五项拍板（见 §9）；**新增 §6 废弃语义**——恢复到过去后，
> 废弃时间线的 trace 与 memory 的处理（v1 缺失，用户指出）。
> v3 变更：**ObjectMemory（EventObjectStore）已落盘且自带 `truncate(eid, step)`，恢复直接调用；StepMemory 落盘化为前置改造（与 EventObjectStore 同构），删除 `rebuild_from_trace`**；术语正名（模拟器世界快照 / LocalTrace 内存表）。
> v4 变更（用户拍板）：**落盘签名统一三元组** (run_id, episode_id, step)——StepMemory 落盘加 run_id、ObjectMemory 补 run_id 字段、模拟器世界快照签名进配对 json；**存储层职责修正**——补范围查询，归档组装归 checkpoint 层；**LocalTrace 内存表迁 DataCenter**（前端单点恢复，观测台数据可恢复）。
> v5 变更（0909，用户拍板）：**取消独立的 `run.json`/`.start.state`**——原因是 v4
> 落地后 `resume_run()` 复用 `load(run_id, episode_id, 0)` 去读 run 锚点，只要这一局
> 跑过 step0（几乎总是）就会先命中它自己的 `step/<eid>/0.json`，`run.json` 永远读
> 不到，`resume_run` 断言必炸——这是实测（`check_restore.py`）踩出来的真实 bug，
> 不是笔误。改法：`RunState`（run 级）跟 `EpisodeRunState`（episode 级）打包进
> **同一份** `step/<eid>/<step>.json`——同一局内 `RunState` 每一步都相同（只有
> `dispatch`/`reflect` 会改它，均发生在局间），一份文件天然带两层信息，彻底
> 消掉"该读哪个文件"的歧义。代价：一局连 step0 都没跑完就崩（`_begin()` 已完成
> 但 `save_checkpoint` 还没来得及写）这个窗口没有任何 checkpoint 可恢复——`.start.state`
> 本来想兜这个窗口但从来没被恢复逻辑读过（死代码），这次一并放弃，需要时再补。
> §3.1/§4/§7.1 的 `run.json`/`save_run`/`latest_run` 相关描述已按此更新，仅保留
> 历史小节说明当时的设计考虑；实现以 `checkpoint_tool.py`/`SPEC.md` 为准。
> 基线：commit `c8b9ab7`。事实清单见同目录 `CHECKPOINT_handoff_2026-09-07.md` §1-2。

## 1. 三级恢复的精确定义

| 级别 | 恢复点 | 恢复后必须成立的等价性 |
|---|---|---|
| **run** | "正在/即将跑 episode X"（放弃 X 的半途进度） | `RunState` 逐字段相等；X 从 step0 重跑 |
| **episode** | 某局 step0 | 该局模拟器=起点状态；pending_observation 在位（**不重调视觉模型**）；本局 StepMemory 空 |
| **step** | 某局第 N 步开局（`save_checkpoint` 之后、`look` 之前） | 模拟器=第 N-1 步末状态；`EpisodeRunState` 逐字段相等；0..N-1 步 StepMemory 在位；trace 前缀逐字节一致 |

**边界（取舍，已确认）**：
- "一样" = **状态等价**，不是未来轨迹逐字节复现（LLM temperature=0 也不保证确定）；
- 恢复粒度 = step 边界（`save_checkpoint` 节点处）；一步中间崩最多损失当步一次模型调用；
- 恢复 API 三元组 **(run_id, episode_id, step) 必填**（用户拍板），三级 = 定位策略不同，恢复管线同一条；
- trace 已落盘前缀的"改写"语义见 §6（截断 + 归档，非静默删除）；
- 只承诺无头语义；watch 模式恢复后画面从存档帧继续。

## 2. 总体机制：显式图节点 `save_checkpoint` + 自研 CheckpointTool

**episode 图新增第 18 个节点 `save_checkpoint`**（用户拍板：加节点在 look 之前）：

```
START → save_checkpoint → look → judge ─(done)→ 收尾链 → END
                              └(否)→ get_action_space → 四路 retrieve
                                    → enrich_observation → think_action → act
                                    → look_after_action → detect_stall → advance_step
                                    → store_step → store_object → save_checkpoint（回到 look）
```

- 图入口改为 `save_checkpoint`：**每一圈边界（含 step0）都在同一个节点里写
  checkpoint**——step0 存档不再由 `_begin` 兼职，职责归一；
- 节点动作：组 SaveReq（**模拟器世界快照**字节——`game.save_state()` 产出的
  PyBoy save-state 二进制，模拟器全部 RAM（按键史/地图演化/NPC 状态）都在里面，
  是唯一无法从事件或记忆重建的东西——+ `EpisodeRunState.model_dump()` +
  trace 游标）调 `CheckpointToolPort.save_step()`。恢复重入时经过它 = 幂等
  重写同号存档，无害；
- **recursion_limit 公式更新**：continue 分支一步走 16 个节点（原 15 + 本节点），
  `16 × max_steps + 20` → **`17 × max_steps + 20`**（`run()` 里同步改，注释
  的节点清单同步）；
- `run()`/`_begin` 不变职责：`_begin` 仍负责 reset/起点存档/**step0 感知**
  （恢复路径跳过 `_begin`，见 §5）。

**为什么不用 LangGraph SqliteSaver**（维持 v1 结论）：checkpointer 只管图状态，
管不了模拟器快照绑定、trace 游标对账、DataCenter 槽、废弃归档四个外部一致性
点，会形成两套真相。

## 3. 落盘签名原则与存储布局

**签名原则（用户拍板）：所有 checkpoint 相关落盘记录显式带三元组签名
`(run_id, episode_id, step)`，不依赖目录位置或命名约定推断。**
现状 `episode_id = f"{run_id}-ep{序号}"`（run_harness.py:361）把 run_id 藏在
名字里——隐式耦合，episode_id 生成规则一变就断；显式签名后对账/归档/跨 run
防串直接拿字段比对：

| 载体 | 签名位置 |
|---|---|
| StepMemory 落盘记录 | **schema 加 `run_id` 字段**（现状没有，前置改造一并加）；文件按 episode 分文件，记录内含三元组 |
| ObjectMemory（`ObjectFactEventBase`） | **加 `run_id` 字段**（现状 episode_id/step 有、run_id 无）；旧文件读取时按 episode_id 前缀推断回填（生成规则稳定） |
| 模拟器世界快照 | 二进制无法内嵌签名 → **配对 json 内嵌三元组**，加载时校验成对 + 签名匹配 |

（v5 起没有独立的 run.json，RunState 签名并入下面的 `<step>.json`）

### 3.1 存储布局（v5：合并单文件，见头部 v5 变更）

```
trace_data/<run_id>/
├── events（JSONL 主前缀；恢复时可能被截断，见 §6）
├── screenshots/                                （现状）
├── checkpoints/
│   ├── voided-<ts>/                            （废弃时间线归档，见 §6）
│   └── step/<episode_id>/
│       ├── <step>.state                        （模拟器存档，二进制）
│       └── <step>.json                         （EpisodeRunState dump ＋ 当时的
│                                                  RunState dump ＋ 游标，唯一提交点）
```

- 写入顺序：**先模拟器存档，再 json（json = 提交点）**；中间 crash = 该号
  checkpoint 无效，恢复回退上一号（对账时校验 json 与 state 成对存在）；
- 全量保留每个 step（百 KB 量级 × 步数，几十 MB 级），GC 留开关 v1 不做；
- 没有单独的 run 级文件：`RunState` 打包进每一步的 `<step>.json`，一份文件
  同时是"这一步的 episode 状态"和"这一局开始前的 run 状态"两份锚点。

## 4. 恢复入口与三级定位

统一签名：`resume(run_id, episode_id, step)`——**三元组必填**（用户拍板）。

| 调用 | 定位 | 数据源 |
|---|---|---|
| step 级 | `(run_id, eid, N)`，N>0 | `step/<eid>/<N>.{state,json}` |
| episode 级 | `(run_id, eid, 0)` | `step/<eid>/0.{state,json}` |
| run 级 | `(run_id, eid, N)`，任意 N | 同一份 `step/<eid>/<N>.json` 里的 `run_state_dump` |

（v5 起三行的数据源本质是同一处：`step/<eid>/<N>.json` 天生带两层信息，
`run_state_dump` 取 run 级、`state_dump` 取 episode 级，不再需要区分文件。
**已知缺口**：一局连 step0 都没跑完就崩（`_begin()` 已完成、`save_checkpoint`
还没来得及写第一份存档）这个窗口没有任何 checkpoint 可恢复——原设想里
`run.json` + `.start.state` 曾想兜这个窗口，但 `.start.state` 从来没被恢复
逻辑读过，是死代码，v5 删除时一并放弃，需要时再补。）

恢复管线（§5）三级共用；差别只在 state 来源与"进 run 图还是 episode 图"。

## 5. 恢复管线（共用主链）

1. **对账**（全部 assert，失败拒绝恢复）：游标 `C` ≤ 文件最大 event_id 且
   前缀行数 = C+1；快照 `step` == 该局事件流最大 step；run 级另加
   `len(outcomes)==EPISODE_END 数`、`len(attempts)==len(goals)`；
   `step/<eid>/<N>.state` 与 `.json` 成对存在；
2. **废弃处理**（§6，对账通过后、载入前执行）；
3. `world.load_state(模拟器世界快照)`——**WorldPort 补 `load_state(path)`**；
4. `LocalTrace` 续写打开：`_next_id` = C+1（`trace/store.py:38` 加恢复入口），
   并把截断后的主前缀**回填内存表**（`_events`，api.py 实时数字/SSE/eval_report
   轮询的就是它；对账本来就要通读 JSONL，顺手做，否则观测台实时部分从恢复点
   起才是活的）；
5. 记忆层截断：各 store 调自己的 `truncate(eid, N)`——
   `EventObjectStore.truncate`（**已存在**，semantic_store.py:113）；StepMemory
   落盘化后同构调用（见 §7.0 前置改造）；
6. state = 快照 `model_validate()`（全量 dump，**pending_observation 在位，
   不重调视觉模型**）；
7. DataCenter 单点重建（v4：事件流槽迁入 DataCenter，见 §7.2）：
   `rebuild(事件前缀, RunState.goals)` 一次调用——观测台/SSE/实时数字的全部
   数据源就位，前端恢复 = 重连 DataCenter，不用分别从 trace 与各槽拼；
8. 进图：episode 级/step 级 → `_graph.invoke(state)`（入口 `save_checkpoint`
   幂等重写本号存档后进 `look`，`recursion_limit=(max_steps-step)*17+20`）；
   run 级 → `RunHarness` 走 `begin` 幂等分支（§9.1）重入；
9. 落 `TraceKind.CHECKPOINT_RESTORE`（payload：三元组 + 游标）。

## 6. 废弃语义（v2 新增：恢复到过去后，"未来"的 trace 与 memory 怎么办）

恢复到 `(eid, N)` 时，废弃时间线（该局 step ≥ N 的所有痕迹）按**归档而非删除**
处理——append-only 精神由归档文件延续，主前缀保证消费方零改动：

| 脏数据 | 位置 | 处理 |
|---|---|---|
| trace 事件（step ≥ N 的 OBSERVE/THINK/ACT/MEMORY_WRITE/账单…） | `events` JSONL | **截断主文件到游标 C**，被截行整体搬入 `checkpoints/voided-<ts>/events.jsonl` |
| **ObjectMemory**（`EventObjectStore`，`ep-<eid>.jsonl` 落盘写穿） | `semantic_store.py:42` | **调它自己的 `truncate(eid, N)`（已存在，:113）**——重写文件 + 内存过滤 + `_max_step` 回退；`append` 的 step 单调 assert 正是为恢复后同局重跑准备的；v2 漏了此项。**签名补 run_id**（§3，v4） |
| **StepMemory**（现状内存 `_steps`，**落盘化是前置改造**） | `episode_store.py:56` | 落盘化照 EventObjectStore 同构（写穿 + `truncate` + `_max_step` assert），恢复同构调用；**v2 的 `rebuild_from_trace` 删除**（过时假设：内存 + trace 重建） |
| 跨局摘要 md（废弃时间线里已蒸馏完成的局） | `episodes/<eid>.md` | 对账：截断后 trace 中仍有 `EPISODE_MEMORY_WRITE` 的 episode 集合之外的 md → 搬入 voided 归档 |
| 截图（step ≥ N 的同号文件） | `screenshots/` | **必须搬走**——`_save_screenshot` 撞名会加 `(n)` 后缀，不搬则重跑写错名；按 `screenshot_filename()` 规则计算 step≥N 的文件移入 voided |
| 模拟器世界快照（step ≥ N 的 `.state`/`.json`） | `checkpoints/step/` | 移入 voided（重跑会覆盖同号，但归档保持与截图同一策略） |
| **LocalTrace 内存表**（`store.py:37` 的 `_events`——api.py 实时数字/SSE/eval_report 轮询的是它，不是文件） | 进程内 | 续写打开时回填截断后主前缀 |
| DataCenter 槽 | 进程内 | goals 按 RunState 重发；human_note/review 留空 |

执行顺序（在 §5 第 2 步内）：**对账 assert 全过 → 归档/截断（一个原子的
"移文件+重写 JSONL"操作，先归档后截断）→ 载入模拟器 → 进图**。截断后若进程
再崩，恢复点仍是本次目标 `(eid, N)`，操作可重入（voided 目录带时间戳不冲突）。

**语义声明**：废弃时间线烧掉的模型账已沉没，不计入新时间线成本统计；归档
目录保留全量供审计。对账/报表/replay 一律只读主前缀——**消费方零改动**是
"截断+归档"优于"标记废弃"（所有消费方都要加过滤）的核心理由。

实现注意（v4 修正）：归档所需数据由**存储层的范围查询**提供，checkpoint 层
不碰存储内部——各 store 补/有"按 episode_id + step 区间"的查询
（`EventObjectStore` 已有 `query`/`query_map` 同族，补按局+区间一个；StepMemory
落盘后同构）。`CheckpointTool.void_after()` 的编排 = **范围查询取废弃段 → 写
voided 归档 → 调 store.truncate**。存储层职责 = 存、查、截断三件，归档组装
是 checkpoint 层的事，不进存储层。

## 7. 前置改造与新增契约

### 7.0 前置改造（checkpoint 的依赖，非 checkpoint 本体）

- **StepMemory 落盘化**：`FileEpisodeMemoryStore._steps`（纯内存 dict）改为
  `ep-<episode_id>.jsonl` 落盘写穿，与 `EventObjectStore` 同构（append 写穿 +
  `truncate(eid, step)` + `_max_step` 单调 assert）。没有它，进程死后本局
  StepMemory 回不到内存，step 级恢复不成立。注意 `before/after_frame` 是
  base64 大字段，落盘体积与 GC 策略一并考虑。
- **StepMemory 加 `run_id` 字段**（现状没有）：落盘签名统一三元组（§3）。

### 7.1 新增契约（命名照 617c6eb 规则；**已过时，实现以 `checkpoint_tool_port.py` 为准**）

以下是规划时设想的接口，跟最终落地不完全一致（`save_step`/`save_run` 从没
分开过，落地时一直是单一 `save(req)`；v5 起 `save()`/`load()` 都不再区分
run/step 两级，`latest_run()` 已删除）——保留仅供追溯设计演变：

```
interfaces/tools/checkpoint_tool_port.py
  CheckpointToolPort
    save_step(req)   # 模拟器存档 + EpisodeRunState dump + 游标（save_checkpoint 节点调用）
    save_run(req)    # RunState dump + 游标 + episode_id（dispatch 前调用）
    load(run_id, episode_id, step) -> ...Resp | None
    latest_run() -> ...Resp | None
    void_after(run_id, episode_id, step) -> VoidReport   # §6 归档+截断

schemas/communication/
  FromHarnessToCheckpointToolSaveReq.py
  FromCheckpointToolToHarnessRestoreResp.py
  FromCheckpointToolToHarnessVoidReport.py   # 截断行数/归档文件清单（可落 trace 供审计）
```

- 实现在 `tools/checkpoint_tool.py`：纯读写 + 对账 + 归档；读 trace 通过注入
  trace 目录路径，**不 import harness**；模拟器存档字节由调用方给（tool 不认识
  PyBoy）；装配只在 `build.py`，harness 构造注入 Port。

### 7.2 LocalTrace 内存表迁 DataCenter（v4，用户拍板）

**现状**：`trace/store.py:37` 的 `_events` 内存表是 api.py 实时数字/SSE/
eval_report 聚合的直接数据源——前端可见状态散在两处（DataCenter 三槽 +
trace 内存表），恢复时要两处分别重建。

**改法**：**前端可见状态收拢进 DataCenter**——
- `RunDataCenter` 加**事件流槽**：`publish_event(event)` / `events()` /
  `rebuild(prefix_events, goals)`（恢复用单点重建）；
- `TraceTool.append` 落盘成功后把事件同步 publish 进 DataCenter（写路径双写，
  构造注入，不构成 import 依赖）；
- `LocalTrace` 职责收缩为纯写端：分配 event_id、落盘 JSONL、模拟器截图、
  截断/续写——**内存表职责移除**（`events()` 与 `_events` 删除，消费方改读
  DataCenter）；
- 收益：恢复时前端数据源单点重建（§5 第 7 步）；观测台历史完整可恢复；
  trace 包回归"落盘 + id 分配"单一职责，读端归 DataCenter，与其定位
  （前后端交互中间层）一致。

**连带改动**：`api.py` 的 SSE/实时数字/eval_report 聚合改读
`data_center.events()`；`trace/store.py` 的 `events()`/`_events` 移除。

## 8. 改动触点

| 位置 | 改动 |
|---|---|
| `episode_harness.py` | 新节点 `save_checkpoint`（18 节点）；`recursion_limit` → `17×max_steps+20`；`resume()` 入口（跳过 `_begin`） |
| `run_harness.py` | `begin` 幂等分支（`resumed=True` 跳过启动副作用，§9.1 拍板）；`dispatch` 前调 `save_run`；`resume()` 入口 |
| `trace/store.py:38` | 续写打开（`resume_after_event_id`）；**`_events`/`events()` 移除（迁 DataCenter）** |
| `harness/run_data_center.py` | **事件流槽**：`publish_event`/`events`/`rebuild`（§7.2） |
| `api.py` | SSE/实时数字/eval_report 聚合改读 `data_center.events()` |
| `interfaces/world/world_port.py` + `pyboy_world.py` | 补 `load_state(path)` |
| `memory/episode/episode_store.py` | **前置改造：StepMemory 落盘化**（同构 EventObjectStore：写穿 + truncate + _max_step） |
| `tools/trace_render.py` + `TraceKind.py` | `CHECKPOINT_RESTORE`（28→29） |
| `tools/checkpoint_tool.py` + `interfaces/tools/checkpoint_tool_port.py`（新） | §7 契约实现 |
| `build.py` | 装配注入 |
| `experiment/run_episode.py` / `api.py` | `--resume run_id episode_id step`；`POST /runs/{id}/resume` |
| `tests/test_checkpoint_resume.py`（新） | §10 验收 |

## 9. 判断点拍板记录（2026-09-07 用户拍板）

1. **run 图恢复重入 = B**：`begin` 内幂等分支（`resumed=True` 跳过启动副作用），
   图拓扑不动。
2. **checkpoint = 显式图节点 `save_checkpoint`**（在 `look` 之前、作为图入口）：
   checkpoint 成为图的一等公民，step0 存档职责从 `_begin` 归一到该节点；
   恢复重入经过它幂等重写。代价：18 节点、recursion_limit 公式改 17×。
3. **observation 全量 dump**（≈10MB/百步，换零重建逻辑零对账链）。
4. **观测台 v1 不做**；实现方必须验证前端对未知 kind 的容错（忽略还是炸），
   会炸则占位渲染是硬性验收项。
5. **恢复 API 三元组必填**（run_id + episode_id + step），废弃语义见 §6
   （截断 + 归档）。

### v4 追加拍板（2026-09-07）

6. **落盘签名统一三元组**：StepMemory 落盘加 run_id、ObjectMemory 补 run_id、
   模拟器世界快照签名进配对 json（§3）。
7. **存储层职责**：补范围查询，归档组装归 checkpoint 层（§6 实现注意）。
8. **LocalTrace 内存表迁 DataCenter**：前端可见状态单点化，恢复单点重建（§7.2）。

## 10. 验收标准

```bash
PYTHONPATH= C:/Users/GummiGu/.workbuddy/venvs/pokemon/Scripts/python.exe \
  -m pytest tests/test_checkpoint_resume.py -q
```

1. **step 级等价性**：一口气跑完 vs 第 k 步杀进程→resume→跑完：恢复点 state
   `model_dump()` 逐字段相等；恢复点前 trace 前缀逐字节一致；event_id 严格
   延续；**恢复路径零额外 MODEL_CALL**；
2. **三级各一条用例**：run 级（放弃半途从局边界重跑）、episode 级（step0）、
   step 级（step k>0）；
3. **废弃语义专项**：恢复到 k 后断言——主 JSONL 无 step≥k 旧事件、voided
   归档完整、`EventObjectStore.query` 不含 step≥k 对象事件（重跑 append 过
   单调 assert）、StepMemory 盘上无 step≥k 记录、重跑后截图无 `(n)` 撞名
   后缀、跨局 md 与截断后 trace 对账一致、观测台实时数字含恢复点前历史；
4. **对账拒绝**：篡改快照 step / 截半行 JSONL / state 与 json 不成对 → 恢复炸；
5. **crash 幂等**：模拟器存档已写、json 未写时崩 → 回退上一号成功；
6. 回归：`test_integration_tool_layer.py` 全绿（18 节点后其节点数断言同步改）；
   ruff 不新增债务。
