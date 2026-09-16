# harness —— 模块规格

> 最后更新：2026-09-15 ｜ 活文档：跟随代码更新，与代码冲突时以代码为准

## 一、职责与边界

`pokemon_agent/harness/` 是控制循环本体——用两张 LangGraph 状态图承载一个 run（完整一局游戏）
与其中的每个 episode（一局），也是**全项目唯一写 trace 的地方**（`AGENTS.md` 铁律 6）。

- **分层边界**：harness 只依赖 `tools` / `schemas` / `prompts` 三层，**不依赖 trace 的实现**。
  写账只经 `TraceToolPort.append`（调用账也是它——`calls` 交整条重试链），读账只经 `TraceToolPort.read_events`
  （`run/harness.py::RunHarness.read_events` 是它的薄委托）。
- **两张图 + 一个 context**：`run/` 是 run 级图，`episode/` 是它的子图；`deps.py` 的
  `HarnessDeps` 不属于任何一张图，两图与两个图外入口共用同一份。
- **活对象一个都不进 state**：世界 / 记忆 / 大脑 / trace 这类不可序列化的对象是 `HarnessDeps`
  的字段，由装配处注入；state 只放能 JSON 化的数据。
- **唯一装配点**是 `pokemon_agent/build.py::build_real`；节点是自由函数，依赖只从 `runtime.context` 读。

## 二、目录结构

```
harness/
├── __init__.py         统一出口    deps.py  HarnessDeps（全图唯一 context）
├── interface/          真端口（零依赖 Protocol）：planner.py（Planner）/ reviewer.py（Reviewer）/
│                       planner_context.py / planner_outcome.py
├── brain_planner.py    BrainPlanner（默认 Planner）   console_planner.py   ConsolePlanner
├── console_reviewer.py ConsoleReviewer                file_reviewer.py     FileReviewer
├── null_reviewer.py    NullReviewer / NullPlanner
├── run/                run 级图：harness.py（RunHarness）/ run_entry.py（new_run, close）/
│                       run_graph.py（compile_run_graph）/ run_state.py（RunState）/
│                       nodes/{begin,plan,dispatch,episode,review}.py
└── episode/            episode 级图（子图）
    ├── episode_entry.py / episode_frames.py / episode_graph.py / episode_state.py
    ├── open/     record_observation.py / save_checkpoint.py
    ├── gate/     get_action_space.py / judge.py
    ├── retrieve/ step / global / knowledge / object / merge 五格
    ├── decide/   think_action.py
    ├── press/    act.py / close_step.py / detect_stall.py / perceive_after_action.py
    ├── store/    store_step_episode_memory.py / store_object_semantic_memory/{__init__,rules}.py
    └── close/    close_episode.py / verify_and_summarize.py / retrieve_verify_step_memory.py /
                  retrieve_verify_knowledge.py / extract_knowledge.py（**不在图上**，见第八节）
```

## 三、两张图

### run 图（`run/run_graph.py::compile_run_graph`）

节点（**节点文件名 = `add_node` 的字面量**，住 `run/nodes/`）：`begin` / `plan` / `dispatch` /
`episode` / `review`。其中 `episode` 一格带 `error_handler=episode_error_handler`（`nodes/dispatch.py`）。

| 边 | 类型 | 判据 |
|---|---|---|
| `START` → `begin` | 固定 | 图入口 |
| `begin` → `plan` | 固定 | begin 只校验（表非空、至多一条 `RUNNING`），返回空增量 |
| `plan` → `END` / `dispatch` | 条件 | `lambda s: END if s.done else "dispatch"` |
| `dispatch` → `episode` | 固定 | 派发这一局（`episode` 节点内部 `invoke` 子图） |
| `episode` → `review` | 固定 | 收结算 |
| `review` → `plan` | 固定 | **只有这一条**，刻意不回 `dispatch` |

- **终止条件**：`plan` 出口的 `done` → `END`。`done` 由 `plan` 写（**不是 `review`**）：
  表末检「表里没有任何 `PENDING`/`RUNNING` 条目 **且** 这一版不新增」成立，或
  `PlannerOutcome.done=True` 且 `deps.auto_decide_done`。
- **`review → plan` 是停机前提**：失败目标被盖成 `FAILED`（非活跃终态），表末检才成立；"要不要再开
  一局"必须由 `plan` 读表后表态（`Planner` 显式把 `FAILED` 重开成 `PENDING`），所以没有 `review → dispatch`。
- **`error_handler`**（`nodes/dispatch.py::episode_error_handler`）：只吞 `AgentError`，返回
  `Command(goto="review", update={"outcome": 失败结算})`；别的异常原样抛。签名是 `(state, error)`，
  读不到 `runtime`。

### episode 图（`episode/episode_graph.py::compile_episode_graph`）

按七个功能域注册的节点，**书写顺序 = 执行顺序**（逐行取自 `add_node` 的字面量，无循环）：

```
open:     save_checkpoint, record_observation
gate:     judge, get_action_space
retrieve: retrieve_step_episode_memory, retrieve_global_episode_memory,
          retrieve_knowledge_semantic_memory, retrieve_object_semantic_memory, merge_retrieval
decide:   think_action
press:    act, perceive_after_action, detect_stall, close_step
store:    store_step_episode_memory, store_object_semantic_memory
close:    retrieve_verify_step_memory, retrieve_verify_knowledge, verify_and_summarize, close_episode
```

| 边 | 类型 | 判据 |
|---|---|---|
| 入口点 → `save_checkpoint` → `record_observation` → `judge` | 固定 | 链首三格（`save_checkpoint` 是链边界，见第八节） |
| `judge` → `retrieve_verify_step_memory` / `get_action_space` | 条件 | `state.done` 为真走收尾链，否则进主循环 |
| `get_action_space` → `retrieve_step_episode_memory` → `retrieve_global_episode_memory` → `retrieve_knowledge_semantic_memory` → `retrieve_object_semantic_memory` → `merge_retrieval` → `think_action` → `act` → `perceive_after_action` → `detect_stall` → `store_step_episode_memory` → `store_object_semantic_memory` → `close_step` | 固定 | 一条直线（四路 retrieve 无数据依赖，顺序是图形状要求） |
| `close_step` → `act` / `save_checkpoint` | 条件 | `s.pending_presses` 非空走 `act`（链内小循环），空则回链首 |
| `retrieve_verify_step_memory` → `retrieve_verify_knowledge` / `close_episode` | 条件 | `s.verify_step_entries` 非空进校验，空则直接收尾 |
| `retrieve_verify_knowledge` → `verify_and_summarize` → `close_episode` → `END` | 固定 | 收尾链 |

- **终止条件全在 `judge` 出口**：四类来源——世界结束（`obs.done`）、步数用尽
  （`state.step >= state.task.max_steps`）、停摆（`state.stall_count >= STALL_LIMIT`）、
  模型判定（`verdict.done`）——合成 `done`/`success`。前三类成立也照问一次模型（最后一帧
  仍可能真的达成）；**第 0 步不问模型**。
- **收尾链的每条分支都汇到 `close_episode`**：它写出子图输出键 `outcome`（父侧 `RunState.outcome`
  同名同型），图跑完时恒非 `None`。
- **`EpisodeInput` / `EpisodeOutput`**（`episode_graph.py`）是父子交界的键表，**不是** `compile()` 的
  实参：本仓是形态 B（`run/nodes/episode.py` 那一格里 `graph.invoke(state, …, context=deps)`），
  交界由 `episode_entry` 的两个入口手工完成。

## 四、状态模型

### `run/run_state.py::RunState`

字段：`run_id` / `plan: list[GoalEntry]` / `outcomes: list[FromRunHarnessToEpisodeHarnessRunResp]` /
`episode_goals: list[Goal]` / `task: Task | None` / `episode_id: str | None` /
`outcome: FromRunHarnessToEpisodeHarnessRunResp | None` / `done: bool` / `why: str`。

- `plan` 是**目标表**（不是栈）：每行带 `status` / `attempts` / `parent_id`（`schemas/harness/domain/goal_entry.py`
  的 `GoalEntry`）。`dispatch` 选**第一条 `PENDING`**（表序），`review` 盖章改状态，`plan` append 新条目。
- **不变式：至多一条 `RUNNING`**（`begin` 与 `dispatch` 出入口 assert）。
- `episode_goals` 是**投影**（非终态条目映射成 `Goal`），每局由 `dispatch` 重写；与 `plan` 是两个键。

### `episode/episode_state.py::EpisodeRunState`

字段：`episode_id` / `task` / `step` / `episode_goals` / `observation` / `action_space` /
`step_episode_memories` / `global_episode_memories` / `knowledge_semantic_memory` /
`object_semantic_memory` / `action` / `plan` / `pending_presses` / `pending_observation` /
`stall_count` / `stall_key` / `done` / `success` / `outcome` / `verify_step_entries` /
`verify_knowledge` / `verified_steps`。

- **不变式 `observation.step == step`**：`perceive_after_action` 给新帧盖 `before.step + 1`，
  `close_step` 同时把 `step` 加一；开局那一帧由 `episode_entry.begin_episode` 直接产出（`step = 0`）。
- `step` 单位是**一次小 action（一个键）**；`observation` 在本圈的语义是"这次按键**之前**那一帧"，
  `pending_observation` 是"刚感知、还没扶正"的 `after`。

### 跨节点传递

单图内节点返回增量 dict 合并回 state（`Command` / `error_handler` 例外）。父子图之间按**键名交集**
传递（F1）：父 → 子的键是 `episode_id` / `task` / `episode_goals`（`EpisodeInput`，`dispatch` 写）；
子 → 父的键只有 `outcome`（`EpisodeOutput`，`close_episode` 写）。**反作用**：子图不输出的键，
父侧保持旧值且不报错。

## 五、依赖注入面

`deps.py::HarnessDeps`（`@dataclass`，全图唯一的 context）字段分四带：

| 带 | 字段 | 何时定 |
|---|---|---|
| 依赖 | `game` / `memory` / `brain_tool` / `trace`（4 根 Port）+ `reviewer` / `planner`（2 个策略对象） | 装配时注入，整 run 不变 |
| 开关 | `auto_push_goals` / `auto_decide_done` | 构造时定，`plan` 读 |
| 记号 | `run_id` / `world_reset_done` | 整 run |
| 账 | `frame_before` / `frame_after`（覆盖式帧槽，键里带 `episode_id`） | 单帧 |

- **谁装配**：`build.py`（唯一 new 具体实现处）造出 `HarnessDeps`，交给 `RunHarness.__init__(deps)`；
  `reviewer` 缺省 `NullReviewer`、`planner` 缺省 `BrainPlanner`（两者**恒非空**）。
- **注入到哪些节点**：所有节点经 `runtime.context` 读（唯一读法 `runtime.context.<字段>`）；
  `context_schema=HarnessDeps` 在两张图的 `StateGraph(...)` 上都声明成**同一个类型**（F10：子图声明不被
  校验，声明成别的会是静默地雷）。
- **一次 run 一份**（F11）：框架不重建 context；跨 run 复用会让第二次 run 带着上一次的帧残留。
- 帧槽写入口唯一是 `episode/episode_frames.remember_frame()`（产出方：图外的 `begin_episode` 与
  图内每键的 `perceive_after_action`）；唯一读者是步尾 `store_step_episode_memory`。

## 六、人在环与可插拔

`interface/` 只有两个零依赖的 Protocol：

- **`Planner`**（`interface/planner.py`）：`plan(ctx: PlannerContext) -> PlannerOutcome`。
  `PlannerContext` 装规划素材（`run_id` / `plan` / `index` / `details` / `objects`）；
  `PlannerOutcome` 分三路产出（`entries` 新增 / `updates` 定点更新 / `done` 收手），
  `updates` 只允许 `ALLOWED_UPDATE_STATUSES = {PENDING, ABANDONED}`。
  失败契约：**抛异常**，不返回空产出（空产出是"我没有意见"这个正常结论）。
- **`Reviewer`**（`interface/reviewer.py`）：`inject(req) -> str`（**插话**，空串 = 没意见）与
  `audit(req) -> resp`（**审**，永远返回一个表态，没答复按认账）。

| 协议 | 实现 | 文件 | 适用 |
|---|---|---|---|
| Planner | `BrainPlanner` | `brain_planner.py` | 默认：模型读记忆 + 目标表自主规划 |
| Planner | `ConsolePlanner` | `console_planner.py` | 人驾驶：一个目标一行地写（读 stdin，阻塞无超时） |
| Planner | `NullPlanner` | `null_reviewer.py` | 无头且要显式关掉规划：不新增、不表态（须显式传） |
| Reviewer | `NullReviewer` | `null_reviewer.py` | 无头：不插话、不推翻 |
| Reviewer | `ConsoleReviewer` | `console_reviewer.py` | 人在同一终端：超时 `CONSOLE_REVIEW_TIMEOUT`（默认 30s） |
| Reviewer | `FileReviewer` | `file_reviewer.py` | 驱动方无终端：请求/回应走盘上文件，缺省 `DEFAULT_TIMEOUT = 300.0`；`audit()` 恒认账 |

- **插话点在三处节点**：`plan`（`PlannerOutcome`）、`think_action`（`Action`）、`judge`（`JudgeVerdict`）
  ——都是"节点内的同步函数调用"，不加图节点。**审点只在 `review`**（`audit()`）。
- `plan` 的顺序是"问 `Planner` 要一版 → 给人看这一版、收插话 → 落表"；不满意就带着那句话重问，次数不设上限。

## 七、trace 写入

- **写入面**：`TraceToolPort`（`tools/interface/ports.py`）的 `append` / `read_events`
  （0916 起写口只有 `append`——批量口 `append_model_calls` 已删，调用账的 `calls`
  交整条重试链）。
- **`kind` 与 `type` 的关系**：`kind` 是**账名**，唯一词表是 `schemas/harness/domain/trace_kind.py::TraceKind`
  （`StrEnum`，值就是落盘封套上的 `kind`，tool 层无翻译表）；`type` 是**粗类**，7 个常量住
  `trace/datastore/trace_event.py::EventType`：`model_call` / `error` / `llm_outcome` / `view` /
  `act` / `memory_io` / `lifecycle`。"哪个节点产出了什么"全部由 `kind` 回答。
- **事件形状**：`schemas/harness/domain/trace_event.py::TraceEvent`（六字段 `uuid` / `kind` /
  `type` / `ts` / `meta` / `content`）；`meta` 装 `{source, run_id, episode_id, step}`，`source` =
  发账位置（节点名或图外入口名）。

| 位置 | kind |
|---|---|
| `run/run_entry.py`（图外） | `RUN_START` / `RUN_END` / `RUN_ERROR` |
| `episode/episode_entry.py`（图外） | `EPISODE_START` / `EPISODE_ERROR` |
| `run/nodes/plan.py` / `run/nodes/review.py` | `PLAN_VERDICT` / `WRITE_EPISODE`（空章版） |
| `open/record_observation.py` / `gate/get_action_space.py` | `OBSERVE` / `GET_ACTION_SPACE` |
| `gate/judge.py` | `JUDGE_VERDICT`、`JUDGE_CALL`（+ 失败 `CALL_EXHAUSTED`） |
| `decide/think_action.py` | `THINK`、`DECIDE_CALL`（+ 失败 `CALL_EXHAUSTED`） |
| `press/` 四格 | `act`→`DO_ACTION`；`perceive_after_action`→`AFTER_ACTION`+`PERCEPTION_CALL`；`detect_stall`→`STALL_CHECK`；`close_step`→`STEP_ADVANCE` |
| `store/` 两格 | `store_step_episode_memory`→`WRITE_STEP`；`store_object_semantic_memory`→`WRITE_OBJECT` |
| `retrieve/`（五格） | `READ_STEP` / `READ_GLOBAL` / `READ_KNOWLEDGE` / `READ_OBJECT`（`merge_retrieval` 不写账） |
| `close/` | `retrieve_verify_step_memory`→`READ_VERIFY_STEP`；`retrieve_verify_knowledge`→`READ_VERIFY_KNOWLEDGE`；`verify_and_summarize`→`VERIFY_CALL`/`VERIFY_VERDICT`/`SUMMARIZE_CALL`/`WRITE_EPISODE`（+`SUMMARY_PARSE_ERROR`、失败 `CALL_EXHAUSTED`）；`close_episode`→`EPISODE_END` |

`save_checkpoint`、`merge_retrieval`、`run/nodes/begin.py`、`run/nodes/dispatch.py`、`run/nodes/episode.py`
与 `episode_error_handler` 不写任何账（`episode` 的边界账在 `episode_entry` 里落）。

## 八、当前状态与已知缺口

- **`extract_knowledge` 已摘出 episode 图**（`close/extract_knowledge.py` 仍在仓库，`add_node` 里没有它）：
  用户定「knowledge 由人管理」，`verify_and_summarize` 直接接 `close_episode`。接回去要动图里三行
  （import + `add_node` + 把直边换回条件边）。遗留：`EpisodeRunState.verified_steps` 现在**只有写方、
  没有读方**。
- **`save_checkpoint` 空转**：存档实现与恢复链已删，本仓只有"新开一 run"一条路径，`RunHarness` 无
  `resume`；该格保留位置与名字，仍是"链边界"的位置语义所在。
- **`TraceKind.PLAN_CALL` 无写点**：词表（`trace_kind.py`）与渲染表（`tools/trace/render.py`）里都在，
  但 harness 内没有 `append` 它的地方（grep `TraceKind.PLAN_CALL` 只命中词表/渲染表）。
- **`FileReviewer.audit()` 一期恒认账**：run 级"这一局算成算败"还没有推翻入口。
- **`run` 图的 `plan` 出口只有两条**（`done → END` / 否则 `dispatch`）：`plan` 的来路只有 `begin`
  或 `review`，不存在"表非空但没 `PENDING`"的可达状态，因此没有第三条边。
- **两条机械核对的脚本已不在仓库**（2026-09-15 复核）：`scripts/check_graph_phases.py`
  （抽 `add_node` 的字面量与观测台相位表逐条比对、核对"节点名 = 实现文件名"、`Runtime[...]`
  类型参数、"两个键都存在于两侧 state"）与 `scripts/check_imports.py`（全仓 import 守卫）
  都已删。**上面那几条"图长什么样"的核对现在没有可执行的守卫**，相关 docstring 已改成
  "曾经有"的措辞（`episode_graph.py` / `deps.py` / `save_checkpoint.py` / `run/nodes/begin.py`
  / `run/nodes/episode.py`）。`scripts/` 下现存的自包含检查只剩下
  `check_trace_self_contained.py` 与 `check_world_self_contained.py`（两个都还在）。
