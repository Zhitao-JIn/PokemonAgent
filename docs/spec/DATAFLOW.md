# 数据流与事件总表（DATAFLOW）

> 最后更新：2026-09-15 ｜ 活文档：跟随代码更新，与代码冲突时以代码为准
> 串起外壳 → run 图 → episode 图 → 每步六件事 → 收尾蒸馏 → trace 落盘；总表由
> `.workbuddy/scratch/extract_trace_table.py` 从代码抽出（`TraceKind` / `_RENDERERS` / `kind=TraceKind.*`）

## 一、端到端一张图

```
experiment/real_check/check_harness.py  ← 外壳，**不包装信封**，只传裸字段
   build_real(rom, state_file, …, run_id=…, reviewer=…, planner=…) → (RunHarness, GameTools)
   harness.run(run_id=…, goals=[Task, …])

run_entry.new_run（图外编排）
   ① RUN_START（meta.source = run_entry.new_run）
   ② RunState(run_id=run_id, plan=initial_plan(goals))；deps.run_id = run_id
   ③ graph.invoke(state, {"recursion_limit": RUN_RECURSION_LIMIT}, context=deps)
        └─ 异常 → RUN_ERROR 后**原样抛**（不吞）
   ④ run_entry.close：RunResp → RUN_END → 拆成 (outcomes, total, succeeded, success_rate)

run 图（compile_run_graph，5 个业务节点 + 1 个 error_handler）
   begin ─► plan ─► dispatch ─► episode ─► review ─► plan（回环）
              └─(done)→ END                    review 出口只有一条：回 plan
   · begin     只校验状态、返回空增量，**不写账**
   · plan      Planner.plan(ctx) → Reviewer.inject（插话循环，不满意带话重问）→ 落表 → 表末检判 done
   · dispatch  取**第一条 PENDING**、盖 RUNNING、episode_id = f"{run_id}-ep{n}"，纯前置不落账
   · episode   节点内 graph.invoke **episode 子图**（形态 B：父子各算各的 limit）
   · review    收结算 → 盖章 COMPLETED|FAILED（机械事实）→ 亮给人审 → 给这一局补记忆章
```

```
episode 图（compile_episode_graph，20 个业务节点；7 个功能域包）
   episode_entry.run_new（图外编排）
     ① begin_episode：EPISODE_START → game.reset()（**只有本 run 首局**）→ 感知第 0 帧
        → EpisodeRunState(episode_id, task, episode_goals, observation)
     ② graph.invoke(state, {"recursion_limit": episode_budget(task, step)}, context=deps)
          └─ 异常 → EPISODE_ERROR 后**原样抛**
     ③ close：取出 graph 内 close_episode 已落账的 outcome

   每步（链首）：save_checkpoint → record_observation → judge
       ├─ done ─► retrieve_verify_step_memory ─(verify_step_entries 非空)─► retrieve_verify_knowledge
       │            └─► verify_and_summarize ─► close_episode ─► END
       │          （entries 为空时 retrieve_verify_step_memory **直落** close_episode）
       └─ 未 done ─► get_action_space → retrieve_step / global / knowledge / object
                        → merge_retrieval → think_action
                        → act → perceive_after_action → detect_stall
                        → store_step_episode_memory → store_object_semantic_memory → close_step
                             ├─ pending_presses 非空 ─► act（链内小循环：不再检索、不再决策）
                             └─ 空 ─► save_checkpoint（回到链首重新决策）
```

## 二、两条图的接力（run → episode）

- **交界是一张三键表**（`episode_graph.EpisodeInput`，**不是** `compile(input_schema=…)` 的实参）：
  `episode_id`（dispatch 写 → 每个节点的账）、`task`（栈顶目标 → `judge` 的判据）、
  `episode_goals`（整栈投影 → 判只判 `episode_goals[-1]`）。传递靠 `RunState` 与
  `EpisodeRunState` 的**键名交集**，没有别名机制。
- **回程只有一个键**：`EpisodeOutput.outcome`（本局结算），**必须由子图自己写出**
  ——子图不输出的键父侧保持旧值，不写就会让 `review` 读到上一次派发的陈旧结算，而且不报错。
- **两层各有一个 limit**：`episode_entry.episode_budget(task, step)`
  = `(task.max_steps - step) * (NODES_PER_DECISION + NODES_PER_PRESS) + RECURSION_MARGIN`
  ——贴身的那道，按"这一局还能跑几步"逐局算；run 级只留一个可调**闸门** `RUN_RECURSION_LIMIT = 200_000`
  （形态 B 下父子计数独立，run 级没有可算的预算）。
- **两个图外入口**：`run_entry.new_run`（起一个 run）/ `episode_entry.run_new`（run 起一局）——
  刻意不同名，避免 `grep run_new` 撞出两处却在不同层级。它们也是 `meta.source` 里
  两个"位置名"（`run_entry.new_run` / `episode_entry.begin_episode` / `episode_entry.run_new` / `run_entry.close`）。
- **`HarnessDeps` 是全图唯一的 context**：两张图 + 两个图外入口共用一份；节点是自由函数，
  依赖只从 `runtime.context` 读。

## 三、一步之内发生了什么

`max_steps` 数的是**键**（一次小 action 一步）。按 `node_io` 的三段模板，一步分三种身形，
顺序即图的拓扑，也就是**输入依赖的顺序**：

| 段 | 节点（`add_node` 顺序） | 产出 |
|---|---|---|
| **决策边界步**（链首） | `save_checkpoint` → `record_observation` → `judge` → `get_action_space` → `retrieve_step_episode_memory` → `retrieve_global_episode_memory` → `retrieve_knowledge_semantic_memory` → `retrieve_object_semantic_memory` → `merge_retrieval` → `think_action` | `observe` / `judge_verdict` / `get_action_space` / 四条 `read_*` / `think`（`save_checkpoint` 与 `merge_retrieval` **不写账**） |
| **链内步**（每按一个键） | `act` → `perceive_after_action` → `detect_stall` → `store_step_episode_memory` → `store_object_semantic_memory` → `close_step` | `do_action` / `after_action` / `stall_check` / `write_step` /（条件）`write_object` / `step_advance` |
| **终止步**（`judge` 判 done 之后） | `retrieve_verify_step_memory` →（条件）`retrieve_verify_knowledge` →（条件）`verify_and_summarize` → `close_episode` | `read_verify_step` /（条件）`read_verify_knowledge` / `verify_verdict` / `write_episode` /（异常）`summary_parse_error` / `episode_end`——**必选只有 4 个**，中间会跳格 |

- **每步的四件事**：**检索**（四路各一条 `read_*`，彼此无数据依赖，顺序是图形状要求的）、
  **决策**（`think_action` 调 `BrainTool.choose`，重试与账单都在 tool 层）、
  **按键**（`act` 是**唯一推世界**的节点）、**感知**（`perceive_after_action`）、
  **判定**（`judge` 一格里判完世界结束 / 步数用尽 / 停摆 / 目标达成四类终止）、
  **写账**（两个 store + `close_step`）。
- **`judge` 出口是唯一分叉**：done → 收尾链；否则 → `get_action_space` 继续。
- **`close_step` 出口是第二个分叉**：队列还有键 → 回 `act`；空了 → 回链首 `save_checkpoint`。
  这就是"一次决策摊平成一串键"的落点：决策调用与四路检索**一回合一付**，
  而 `detect_stall` / 两个 store / `close_step` **每键各跑一次**。
- **收尾链**：`judge` 判 done → 全量 step 记忆检索（`read_verify_step`）→ 校验器
  （`VERIFY_CALL` + `verify_verdict`）→ 蒸馏（`SUMMARIZE_CALL` + `write_episode`）→
  `close_episode` 算结算写 `episode_end`（`reason` ∈ `success` / `stalled` /
  `max_steps_exceeded` / `world_ended`）。

## 四、事件总表

`kind` 就是 `TraceKind` 的值（35 个成员），`type` 是 7 类 `EventType` 之一；
一个 kind 恰好落一个 type（账单那条例外：`model_call` 会在某次尝试失败时**连带**补一条 `call_failed`）。
"生产位置"是写进 `meta.source` 的那个名字。

| `TraceKind` 值 | `EventType` | 由哪个节点 / 位置产生 | `content` 放什么 |
|---|---|---|---|
| `run_start` | `lifecycle` | `run_entry.new_run` | `goals`（目标文字数组）、`success_criteria`（平行数组） |
| `run_end` | `lifecycle` | `run_entry.close` | `total`、`succeeded`（均 `str`） |
| `run_error` | `lifecycle` | `run_entry.new_run` | `error`（异常快照）——不带结算三件 |
| `episode_start` | `lifecycle` | `episode_entry.begin_episode` | `goal`、`success_criteria`、`max_steps` |
| `episode_end` | `lifecycle` | `close_episode` | `success`（小写）、`steps`、`reason` |
| `episode_error` | `lifecycle` | `episode_entry.run_new` | `error`——不记恒定的 `success` / `steps` |
| `perception_call` | `model_call` | `perceive_after_action` | 该次调用账原样（`ok` / `prompt`；成功另带 token 四件 + `raw`） |
| `decide_call` | `model_call` | `think_action` | 同上 |
| `plan_call` | `model_call` | **无写点**（词表与渲染表里有） | 同上 |
| `judge_call` | `model_call` | `judge` | 同上 + `why`（判定依据） |
| `verify_call` | `model_call` | `verify_and_summarize` | 同上 + `verdicts`（对象数组 `{index, reliable, why}`） |
| `summarize_call` | `model_call` | `verify_and_summarize` | 同上 |
| `extract_call` | `model_call` | `extract_knowledge`（**已摘出图**） | 同上 |
| `call_failed` | `error` | 由 `model_call` **连带**产出 | `link`、`exception`（异常类名）、`reason` |
| `call_exhausted` | `error` | `think_action` / `judge` / `verify_and_summarize` / `extract_knowledge` | `link`——不带 `reason`（在同链末条 `call_failed` 上） |
| `summary_parse_error` | `error` | `verify_and_summarize` | `link`（恒 `summarize`）、`reason` |
| `observe` | `view` | `record_observation` | `status`、`facts`（对象）、`goals`（数组）、可选 `frame` |
| `think` | `llm_outcome` | `think_action` | `sequence`（数组）、`thought`、`input`、`output`、可选 `human_note` |
| `do_action` | `act` | `act` | `sequence`（单段数组） |
| `get_action_space` | `act` | `get_action_space` | `names`（数组，掩码结果） |
| `stall_check` | `act` | `detect_stall` | `stall_key`、`stall_count`（`str`） |
| `after_action` | `view` | `perceive_after_action` | `facts`（对象）、`done`、`perceived`、可选 `place` / `frame` |
| `step_advance` | `lifecycle` | `close_step` | `next_step`（`str`） |
| `judge_verdict` | `llm_outcome` | `judge` | `done`、`success`、`stalled`（均小写）、`why`、`input`、`output` |
| `verify_verdict` | `llm_outcome` | `verify_and_summarize` | `checked`、`unreliable`、`input`、`output` |
| `plan_verdict` | `llm_outcome` | `plan` | `done`、`pushed_goals`（数组）、`why`、可选 `input` / `output` |
| `read_step` | `memory_io` | `retrieve_step_episode_memory` | `query`、`refs`（字符串数组） |
| `read_global` | `memory_io` | `retrieve_global_episode_memory` | 同上 |
| `read_knowledge` | `memory_io` | `retrieve_knowledge_semantic_memory` | 同上 |
| `read_object` | `memory_io` | `retrieve_object_semantic_memory` | 同上 |
| `read_verify_step` | `memory_io` | `retrieve_verify_step_memory` | 同上 |
| `read_verify_knowledge` | `memory_io` | `retrieve_verify_knowledge` | 同上 |
| `write_step` | `memory_io` | `store_step_episode_memory` | 记录本体去坐标与两帧：`before`、`rationale`、`action`、`after`… |
| `write_object` | `memory_io` | `store_object_semantic_memory` | 事件本体：`outcome`、`object_kind`、`place`、`actor_place`、`button`… |
| `write_episode` | `memory_io` | `verify_and_summarize` / `review`（空章版） | 蒸馏各字段 + `markdown`；**章（`goal`/`success`/`steps`）不进** |

`meta.source` 的值域 = 图上 26 个节点名（20 + 6）+ 图外 4 个入口名 + `extract_knowledge`
——`node_io._KNOWN_PLACES` 逐个核，错字 / 空串当场炸。

## 五、正文编码约定

一条落盘事件只有六个字段（`uuid` / `kind` / `type` / `ts` / `meta` / `content`），
`meta` 与 `content` 都是 **JSON 字符串**，`store` 负责序列化；`meta` 恰好四件
（`run_id` / `source` / `episode_id` / `step`，**不多不少**）。

- **顺序只认 `(ts, uuid)`**：文件名是时间递增 uuid，但排序真源是内容里的这两个字段
  （`store.LocalTrace.append` 保证 `ts` 严格递增）；**没有内存事件镜像**，磁盘账本是唯一真相。
- **标量一律 `str()`，布尔一律小写 `true` / `false`**：`node_io.BOOLEAN_FIELDS`
  （`done` / `success` / `stalled` / `ok` / `perceived`）一份扁平名单通吃，**不按账分大小写**。
- **本身就是结构化数据的那几处直接放对象 / 数组**，不再 `json.dumps` 一次（双重编码）：
  `facts` / `sequence` / `verdicts` / `refs` / `names` / `goals` / `success_criteria` /
  `pushed_goals` / 三本写账的正文。`node_io._check_structured_content` 与
  `_check_read_accounts` 守着这一条。
- **能推出来的不写**：`goal_count`、`success_rate`、`count`、`pushed_count`、
  `segment_count` / `press_count`、`observe` 顶层的 `scene` / `overlay`——
  散在正文里的派生值迟早和真相对不上。
- **三本写账的正文就是记录本体**（`render._body` 按各家 `drop` 去掉坐标与章）：
  `_STEP_BODY_DROP` = `episode_id` / `step` / `run_id` / `before_frame` / `after_frame`；
  `_OBJECT_BODY_DROP` = 头三个；`_EPISODE_BODY_DROP` = 坐标 + `goal` / `success` / `steps`。
  `node_io._WRITE_FORBIDDEN_KEYS` 反向核"正文里没多出封套或 `meta` 的键"。
- **画面真源在 `memory/step_memory/*.json` 的 `before_frame` / `after_frame`**；
  `observe` / `after_action` 正文里的 `frame` 是 base64 PNG 的另一份，槽空时键不出现。

## 六、当前状态与已知缺口

- **`extract_knowledge` 已摘出 episode 图**：节点、prompt、`store_knowledge` 都在原位，
  但 `verify_and_summarize` 现在直连 `close_episode`；`state.verified_steps` 因此**只有写方没有读方**
  ——要么一起摘、要么按 `CHANGELOG.md` 第 98 条接回去，别让它长期悬着。
- **`save_checkpoint` 是空转 stub**：存档链整体已删，它仍占图上一格（链边界的位置语义仍成立）。
- **`plan_call` 没有写点**：词表与渲染表都在，harness 里没有 `append` 它的地方。
- **错误族只有三个成员**（`call_failed` / `call_exhausted` / `summary_parse_error`），
  0914 之前是开集（`type(exc).__name__`），现在可逐个登记。
- **`write_episode` 有两个合法生产者**（`verify_and_summarize` 正文版 / `review` 空章版），
  靠 `meta.source` 分开——所以不能按 kind 收成一对一。

### 发现的不一致

- **节点数**：`build.py` 说 episode 子图"21 个节点"、`node_io.py` 说"27 个节点（episode 21 + run 6）"，
  而 `episode_graph.py` 的 `add_node` 与 `node_io.EPISODE_NODES` 都是 **20** 条
  ——实际是 **20 + 6 = 26**（`extract_knowledge` 摘出图之后没跟着改）。以代码为准。
- **`AGENTS.md` 九说 `TraceKind` 的 `content` 逐字段契约由 `tools/trace/render.py` 给出、
  来源记 `docs/spec/DATAFLOW.md` 2.2**：那份 2.2 节随旧文档一起没了，本文档的第四节是它的重建版。
- **`AGENTS.md` 九的字段表与 `schemas/harness/domain/trace_event.py::TraceEvent` 对照后一致**
  （六字段、`meta` 四件、`kind` 与落盘账名同值），无需改正。
