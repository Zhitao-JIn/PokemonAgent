# PLAN_planner_v2 —— run 级规划器改造：状态化任务表 + 记忆索引式披露

> 用户 0914 00:1x 定调：**(a) 渐进披露**（像代码 Agent 那样先读索引/摘要定位、再按需拉详情）
> 与 **(b) 状态化任务表**（像 TodoWrite 那样维护带状态的任务表、每局回来更新状态，
> 而不是只会 push 新目标）**两个都要**。

---

## 0. 落地状态（0914 09:0x 核对，**读这一节比读全文快**）

> **S1–S5 全部落地**（0914 02:36 至 09:0x）。本文已从"待办清单"变成"设计记录"——
> 剩下有价值的只有 §2.5 的不变量清单与二期留缝（§3.3 工具环、§3.2 的详情规则）。
> **以代码为准的三处偏差**记在下面第 3 条里。

| 步 | 落地形态 | 记账 |
|---|---|---|
| **S1** 状态化任务表（§2） | ✅ `schemas/harness/domain/goal_entry.py` 的 `GoalStatus`（五态，类 docstring 就是权限表）+ `GoalEntry`（另加 `parent_id`）；`dispatch` 取第一条 `PENDING`；`plan` 的表末检判 done；`reflect` 并入 `review` | `CHANGELOG.md` 第 76/77 条 |
| **S2** plan 换读口（§3.1–3.2、3.4、3.5） | ✅ `plan._context()` 读 `query_episode_summaries(conditions={"run_id": …})` + `query_object_events()`（`map_id` 已改为可选）；`PlannerContext` 收 `index`/`details`/`objects`；`tests/test_plan_reads_memory.py` | `CHANGELOG.md` 第 79 条 |
| **S5** `Planner.updates`（§2.2 末） | ✅ `PlannerOutcome.updates` + `ALLOWED_UPDATE_STATUSES`；`RunPlan.PlanUpdate`（序号寻址）；`ConsolePlanner` 的 `@序号 放弃\|重开 理由` | `CHANGELOG.md` 第 80 条 |
| **S3** 失败局的 memory 出口（§4 末） | ✅ 正文全空的记录；写入点 `review._leave_chapter()`；"一局恰好一条"（那枚 `chapter_only` 标记 0914 99 连字段一起删了——空不空看正文自己） | `CHANGELOG.md` 第 81 条 / 第 99 条 |
| **S4** 语义抽取（§3.6） | ⏸ **已摘出运行路径**（0914 98）：`extract_knowledge` 曾是收尾链第五格（第 22 个节点）、`Brain.extract()` 第七条链路 → `knowledge_memory/`；用户定「knowledge 由人管理」，节点不再跑，**模块与账都留着**（接回去见第 98 条） | `CHANGELOG.md` 第 82 条（落地）/ 第 98 条（摘出） |

**配套已跟上**（0914，`CHANGELOG.md` 第 83 条）：真机核对清单
（`experiment/real_check/`）补上了这四条改动的判据——`check_harness` 现在会核
"每局恰好一条 `episode_memory`"（S3）、"收尾链第二个分叉两边对上"与"知识账与库
双向一致"（S4）；S2 的**读侧**靠 `planner=NullPlanner() + auto_push_goals=True`
在真机上被走到（开读口、关决策）。**S5 的 `updates` 仍没有被真机覆盖**——
它要 `Planner` 真的吐一条 `update`，本脚本走不到（见 `common.CONTROL_SETUP_HINT`）。

**三处与本文不同（以代码为准）**：

1. **失败落 `FAILED`（终态），不置回 `PENDING`**。本文写的是"置回 PENDING 等重试"，
   实现改成了终态——理由是置回 `PENDING` 会让表末检永远不成立、
   `review → plan → dispatch → review` 无限派发一条必败目标（实测复现）。
   **重试因此变成 `plan` 的显式决策**：`Planner` 读表看见 `FAILED`，自己发一条
   `updates` 把它重开（S5 补上了这个机制，见第 80 条）。
2. **`Planner` 返回的是"要追加的新条目 + 定点更新"，不是整表**。整表重写会
   **静默丢目标**（漏抄一条没人报错）；定点更新每条指名道姓，漏了谁一目了然。
3. **`MAX_PLAN_PUSH` 已删**——目标表的增长由 `Planner` 自己负责，`plan` 不再替它截断；
   现在只剩 `config.PLAN_MAX_NEW_GOALS`，它是**渲进 prompt 的建议数**，不是裁剪。

**二期留缝（还没做，方向已定）**：

- **§3.3 工具环**：让模型自己请求"我要看哪几局的正文"，`_pick_details` 退休
  （信封不用改——`details` 直接换成模型请求的结果）。等 S2 的实跑数据出来再定。
- **召回质量**：`_pick_details` 现在是"最近 1 局 + 全部失败局"这条确定性规则，
  没有相关性排序。冷启动阶段够用，局数上去之后可能要换。


---

## 1. 现状盘点（读码事实）

> **注意**：以下 §1 是 0914 00:2x 的读码快照（`goals` + `attempts` 那个版本）。
> 表已落地，所以 §1.2–§1.3 里"目标栈 / LIFO / 弹出"的说法**已经过时**，
> 只作为设计动因保留——要看现在的形状读 §0 与 `goal_entry.py`。

### 1.1 图拓扑与 plan 的位置

`harness/run/run_graph.py`：

```
begin → plan → dispatch → episode → reflect ─┬─(失败且重试未耗尽)→ dispatch
      ↑                                       └─(否则：弹出)→ review
      └──────── continue / retry ─────────────────────────────┤
        (done / plan 连续失败)                                └─ stop → END
```

- `plan` 出口三路（`run_graph.py:79-94`）：`plan_failed` → `review`；`done` → `END`；
  **`not s.goals` → `review`**；否则 → `dispatch`。
- `reflect` 出口两路（`run_graph.py:97-101` + `_should_retry`，`run_graph.py:110-123`）：
  `outcome 失败 且 goals 非空 且 goals[-1] == task` → 直连 `dispatch` 重试；否则 → `review`。

### 1.2 plan 现在读什么、写什么

`harness/run/nodes/plan.py`：

| | 内容 |
|---|---|
| 读 | `state.goals`（目标栈）；**`deps.trace.read_events()`——该 run 全量事件流**（`plan.py:163`） |
| 折 | `tools/prompts/run_plan.py::history_lines`（`run_plan.py:19-44`）只读 `LIFECYCLE` 的 `episode_start` 与 `episode_end`/`episode_error`，折成 `- epN: 目标 → 成功/失败（N 步，reason）` |
| 问 | `BrainToolPort.plan(PlanOnceReq{run_id, goals, events, max_push})`（`tools/interface/ports.py:126`）→ `Brain.plan(prompt, goal_stack, history, max_push)` |
| 得 | `RunPlan{push_goals: list[PlanGoal{goal, success_criteria, max_steps}], done, why}`（`brain/interface/domain/run_plan.py:22`） |
| 写 | `to_tasks()` → **append 到 `state.goals`**（`plan.py:225-242`）；落 `PLAN_CALL` + `PLAN_VERDICT` 两条账 |

**关键事实**：`history_lines` 的输入是 trace，**不是 memory**。这是"存下来的东西只有 memory
里的东西"这条约束下唯一的错位。

### 1.3 目标栈语义：纯 LIFO + 弹出即消失

`harness/run/run_state.py`：

```python
goals: list[Task]      # 栈，栈顶 = goals[-1]
attempts: list[int]    # 平行计数，invariant: len(attempts) == len(goals)
outcomes: list[FromRunHarnessToEpisodeHarnessRunResp]
```

- 入栈：`plan` 原序 append（`plan.py:114-122` 的注释强调"后压的先做"，顺序曾被反转过一次，
  事故见 `CHANGELOG.md` 2026-09-04）。
- 出栈：`reflect` 成功必弹（`reflect.py:49-54`）、重试耗尽强弹（`reflect.py:56-61`）。
  **被弹掉的目标从状态里彻底消失**——只剩 `outcomes` 里一条不带 goal 的结算，
  要回看它是什么目标只能去 trace 里捞 `episode_start`。
- 消费：`dispatch` 取 `state.goals[-1]`（`dispatch.py:54`），投影成 `episode_goals` 给子图。
- 人工编辑：`POST /runs/{id}/goals` → `FromFrontendToRunHarnessSubmitEditReq{kind:"push", goals}`（整栈原子替换）
  → `apply_goals_edit`（`plan.py:67-79`），`attempts` 按 `task_id` 找回。

**目标上没有"状态"这个概念**：一个目标要么在栈上、要么不存在。

### 1.4 记忆四族与现有读口

| 家族 | 落盘 | 一条 = | 现有读口 |
|---|---|---|---|
| `episode_memory` | `memory/episode_memory/*.md`（7 条） | 一整局 | `query_episode_summaries(conditions)`——**纯等值过滤、全量、不排序不截断**（0914 改造） |
| `step_memory` | `memory/step_memory/*.json`（32 条） | 一步 | `query_episode_steps(episode_id)`（升序全量）/ `query_recent_steps(episode_id, limit)` |
| `object_memory` | 空 | 一格 | `query_object_events(map_id, before_step)` / `query_object_events_at(place)` |
| `knowledge_memory` | `memory/knowledge_memory/*.md`（12 条，离线先验） | 一条先验 | `query_knowledge(query, limit)`——纯语义检索 |

`EpisodeMemory` 的结构（0913 语义修正后）= **来源章**（`episode_id`/`run_id`/`goal`/`success`/`steps`）
+ **派生正文**（`summary`/`reusable_patterns`/`critical_decisions`/`failure_points`/
`quality_score`/`tags`/…/`markdown`），`render()` 输出"第一行是章、往下才是正文"。

**这个结构本身就是为渐进披露准备的**：章 = 索引行，正文 = 详情。

### 1.5 三处具体缺陷（本方案要解决的）

1. **plan 读 trace 不读 memory**（`plan.py:163`）。trace 里 78% 是 prompt/raw 这类噪声，
   而 memory 已经是对它的蒸馏；且与"持久面只有 memory"这条约束相矛盾。
2. **失败的痕迹断链**。重试耗尽的局：`reflect` 把目标弹掉（run state 面零痕迹），
   且 `dispatch.episode_error_handler`（`dispatch.py:65-95`）拿不到 runtime、
   一条 memory 也不写（memory 面零痕迹）。**plan 因此无从知道"这个目标我试过、跑挂了"。**
3. **顺序语义反直觉**。LIFO + "后压的先做"要求模型自己把列表**倒着排**（`run_plan.md`
   用了整整一段说明这件事），是已出过一次事故的地方。

---

## 2. 设计 B：状态化任务表

### 2.1 数据形状

把 `RunState.goals` / `attempts` 两个平行列表收敛成**一张表**：

```python
# pokemon_agent/schemas/harness/domain/goal_entry.py（跨层契约，与 TraceEvent 同级）

class GoalStatus(StrEnum):
    PENDING   = "pending"     # 待派发
    RUNNING   = "running"     # 正在跑（dispatch 已选、reflect 未回）
    COMPLETED = "completed"   # 本局判成功
    FAILED    = "failed"      # 重试预算耗尽，放弃该目标
    ABANDONED = "abandoned"   # 主观放弃（还没跑或没跑完就不做了）

class GoalEntry(BaseModel):
    task: Task                              # 复用 brain 的领域模型，一字不改
    status: GoalStatus = PENDING
    attempts: int = 0                       # 已派发次数（原来是平行列表，现在贴着目标）
    last_episode_id: str | None = None      # 最近一次派发 → 回查 step_memory / trace 的指针
    note: str = ""                          # 放弃/重开的理由（人或模型给）
```

`RunState` 变为：

```python
plan: list[GoalEntry]                       # 替代 goals + attempts
outcomes: list[...]                         # 不动
```

**为什么 `Task` 不动**：`status` 是 run 级编排概念，不是任务本体的属性；`Task` 还出现在
`WorldPort.reset()` / `GameToolPort.reset()` 的签名里，往里塞 `status` 会污染 world。

**为什么 `attempts` 从平行列表搬进条目**：现有 invariant `len(attempts) == len(goals)`
是被 assert 守着的（`begin.py:27` / `dispatch.py:53` / `reflect.py:46`）——两个平行列表要
靠纪律保持同步，这本身就是设计味道。合并成一条记录后，这条 invariant 从"要维护的约束"
变成"结构上不可能违反"。

**`last_episode_id` 是 (a) 与 (b) 的接缝**：任务表给的是"我做过哪些目标"，
这一列是把表上的一行接到 memory 里那一局详情的**指针**。

### 2.2 状态机与写入权限（本次设计的核心裁定）

**一句话：`status` 这个字段，不是谁都能写的。**

"盖章" = 往 `status` 上写一个值。写之前先分清这件事属于哪一类：

- **机械事实**（这台机器就能判定）：派发了没有、本局成功了没有、重试预算耗尽了没有
  —— **只有 harness 能盖**，模型和人都没有这个权限；
- **主观决策**（是一个判断，不是事实）：我不想做这个目标了、我要把这条重开
  —— 由模型或人给。

| 迁移 | 谁做 | 触发 |
|---|---|---|
| `PENDING → RUNNING` | `dispatch` | 选中并派发（`attempts += 1`、`last_episode_id = episode_id`） |
| `RUNNING → COMPLETED` | `reflect` | `outcome.success` |
| `RUNNING → PENDING` | `reflect` | 失败且重试预算未耗尽（等价于现在的"栈顶保留"） |
| `RUNNING → FAILED` | `reflect` | 失败且重试预算耗尽（等价于现在的"强制弹出"） |
| `FAILED/COMPLETED → PENDING` | `review`（RETRY）/ 人工 | 重开（`attempts` 清零，等价于现在的 `attempts + [0]`） |
| 新增 → `PENDING` | `plan`（模型） | 新目标 |
| 任意 → `ABANDONED` | `plan`（模型）/ 人工 | 主观放弃 |

**理由**：`success` 是机械判定（`judge` 的裁决，`close_episode.py` 读 `state.success`）。
记忆那边已经立过一条硬规则——**R2「摘要不当证据：任何'必须为真'的判断走机械来源，
不走 LLM 叙述」**（0913 23:08 记录，与 judge/verify 的 `reason=False` 同源）。
让 LLM 决定"这条 completed 了"就是把 R2 违反一次。所以 `COMPLETED`/`FAILED` **只能**由
harness 从 `outcome` 推导，模型**没有**写这两个状态的权限。

模型新增的能力面只有一条：**`abandon`（放弃）**——"这个目标我不打算做了"。
它是**判断**不是事实，所以该由模型说（人同理）。

**这一条的现状（0914 03:2x）**：`GoalStatus.ABANDONED` 已经定义好了，好几处
docstring 都指认它是"唯一人能直接写的状态"，**但全仓没有一行代码写它**——
`Planner.plan()` 只会**追加**新条目（`plan.py:101`），改不了已有条目的状态，
所以今天没有任何消费者能真的弃掉一条目标。要补，就得给 `Planner` 的产出加一层
"改已有条目"的面，两种形状：

- **(i) 产出带一个 `updates`（`task_id` → 新状态 / `note`）**，`plan` 节点先照改、
  再 append 新条目。改动面小，且天然带校验：`updates` 里**只允许**出现
  `PENDING`（重开）与 `ABANDONED`（放弃）两个值，其余状态照旧是 harness 的
  盖章地盘——§2.2 那张表直接就是校验规则。
- **(ii) 产出升成"整表 vs 上一版"的差量**——表达力最强，但模型要背格式负担，
  且"模型漏抄一条"会静默丢目标（铁律里的静默失败）。

**推荐 (i)**。

### 2.3 顺序：表序即优先级，LIFO 退役

- 表的**行序 = 优先级**，第一个 `PENDING` 先做。模型不再需要"把最先做的排在列表最后"
  这种逆序约定——`run_plan.md` 里那整段说明和 09-04 的事故根源一起消失。
- `dispatch` 的选取规则收敛成一条：**取第一个 `status == PENDING` 的条目，置 `RUNNING`**。
  重试路径下 `reflect` 已把该条目置回 `PENDING`，所以 `dispatch` 不需要认识"重试"这个概念。
- `FAILED` / `COMPLETED` 的条目**留表**，不删除。plan 每次读全表 → 直接看见"试过什么、
  成没成"，缺陷 2 的 run-state 面被堵上。

### 2.4 各改动点

| 文件 | 现在 | 改成 |
|---|---|---|
| `harness/run/run_state.py` | `goals` + `attempts` | `plan: list[GoalEntry]`（字段注释重写） |
| `harness/run/nodes/dispatch.py` | `top = goals[-1]`；`attempts[-1]+1`；`project_goals(goals)` | 取第一个 PENDING → RUNNING；`project_goals` 只投影**未完成**的（给子图全局视野） |
| `harness/run/nodes/reflect.py` | `goals[:-1]` / `goals` | 按 §2.2 改状态，不删条目 |
| `harness/run/nodes/plan.py` | `state.goals + pushes`；`apply_goals_edit` | 新增 PENDING 条目；应用 `abandon` 指令 |
| `harness/run/nodes/review.py` | `goals[-1] == task`；RETRY 压回 | 按 `last_episode_id` / RUNNING 定位；RETRY 置回 PENDING |
| `harness/run/run_graph.py` | `not s.goals` / `_should_retry` | `无 PENDING` / `第一个 PENDING 还是刚失败的 `Task`` |
| `harness/run/nodes/episode.py` | `stack=state.goals` | `stack=` 表里未完成的 Task 列表 |
| `harness/interaction.py` + `harness/run/harness.py` | `latest_goals() -> list[Task]` | 返回整表（观测台要显示状态） |
| `schemas/frontend/.../SubmitEditReq.py` | `goals: list[Task]` | `plan: list[GoalEntry]`（整表原子替换，含状态） |
| `schemas/harness/.../ReviewReq.py` | `goals: list[Task]` | 整表 |
| `brain/interface/domain/run_plan.py` | `push_goals` | 保留 + 新增可选的 `abandon` 指令（见 §7-Q3） |

> **落地时与这张表的两处偏差**（0914 真机起跑时才暴露，账见 `CHANGELOG.md` 第 85 条）：
> ① `dispatch` 那格的投影**不是"只投影未完成的"**——它会把**正在跑的那条排到最后**
> （`active_stack()`）。子图把列表**最后一位**当"你现在要完成的"（`judge` 判
> `goals[-1]`、`decide_action` 给它标 `← 你现在要完成的`），而 `dispatch` 取的是
> **第一条 `PENDING`**：表里有同层兄弟时，"照表序"会让子图拿兄弟 A 去判兄弟 B。
> ② 失败由 `review` 盖 **`FAILED`**（终态），不是表里写的"RETRY 置回 `PENDING`"
> ——置回 `PENDING` 会让"无活跃条目 + planner 不新增"这条表末检永不成立、
> `review → plan → dispatch` 无限派发（`tests/test_run_graph_termination.py` 钉着它）。
>
> 这张表是**当时的计划**，不改写；上面两条是"照它实现会错"的地方。

**brain 本体零改动**：`BrainPort.plan(prompt, goal_stack, history, max_push)` 四个签名参数
一个不动——`goal_stack` 从"栈的行"变成"表的行"（渲染层的事），`history` 从"trace 折的行"
变成"memory 折的块"（渲染层的事）。**这正是铁律 2 想要的形状**：换世界/换记忆不用改大脑。

### 2.5 不变量（写成 assert）

- **至多一个 `RUNNING`**（`reflect`/`dispatch` 出入口检查）——"现在在做哪一条"必须唯一。
- `dispatch` 出口：被选中的条目 `status == RUNNING` 且 `last_episode_id == state.episode_id`。
- `reflect` 入口：恰好一个 `RUNNING` 且它就是刚回来的那一局（按 `last_episode_id` 对）。
- `COMPLETED`/`FAILED` 的条目 `last_episode_id` 非空——**章不能没有来源**（没有来源的状态
  等于一个不可追溯的断言）。

### 2.6 `done` 判据

现在：`not state.goals and not pushes`（`plan.py:209`）。
表化后 FAILED/COMPLETED 条目留表，`not plan` 永远为假——判据必须换成：

> **表里没有任何 `PENDING`/`RUNNING` 条目、且模型不新增** → 可判 done。

好处：模型看到表上还有 `FAILED` 的行，可以选择"重开 / 换个做法 / 收手"三选一，
而不是像现在这样失败目标一弹出 plan 就自动倾向 `done`。
护栏：若表进入"全完成/全失败"且模型不表态且 `auto_decide_done=False`，
条件边照旧路由去 `review` 问人（`run_graph.py:89` 那条分支的语义平移）——不会死锁。

---

## 3. 设计 A：记忆索引式披露

### 3.1 索引 = `episode_memory` 的来源章（零新增存储）

**不新开记忆族**（用户口径：不为几个例子开新家族）。`EpisodeMemory` 已经是
"一章 + 一正文"的结构，**章就是索引行**：

```
- [ep3] ✅ 走到常磐市 → 12 步（success）
- [ep4] ❌ 和门口的训练师对话 → 8 步（max_steps_exceeded）
- [ep5] ❌ 进商店买伤药 → 30 步（stalled）
```

`history_lines` 的输入从 `list[TraceEvent]` 换成 `list[EpisodeMemory]`，
输出的行数不变、信息量更大（现在那行只有 `goal + 成败 + 步数 + reason`，
换过来还白得 `quality_score` / `tags`）。

### 3.2 详情按需预取（一期策略）

一期不做工具环，用一条**确定性选题规则**决定哪些局的正文进 prompt：

1. 最近 1 局 —— 全正文（刚发生的事最相关）；
2. 所有 `success == False` 的局 —— 全正文（失败是最该被看见的原料，
   对应缺陷 2 的 memory 面）；
3. 其余局 —— 只给索引行。

`EpisodeMemory.render()` 已经是"章 + 正文"的形态，直接可用。选中的详情进
`details` 块，未选中的只有索引行——**这就是渐进披露的最小可用形态**：
上下文里装的是"全部局的骨架 + 少数几局的肉"，而不是"全量 trace 的倾倒"。

### 3.3 工具环（二期，留缝）

真·渐进披露是**模型自己请求详情**（代码 Agent 的 glob/grep/read）。它的形状：

```
plan ─(吐 ToolCall)→ plan_tool ─(回执行结果)→ plan ─(吐 RunPlan)→ dispatch
```

- 新增 `plan_tool` 节点（run 图多一格），照 episode 图 `think_action → act` 的手法；
- `BrainPort` 新增一个"带工具的规划"能力面（或让 `plan` 的返回能是 `ToolCall | RunPlan`）；
- 每次工具往返记一笔 `PLAN_CALL` 账。

**一期把缝留好**：`PlanOnceReq` 里 `index`（索引，必给）与 `details`（预取详情，可稀疏）
**分成两个字段**，而不是合成一个字符串。将来 `details` 变空、加工具环，信封不用改。

**为什么一期不做**：当前 run 只有 7 局，索引一行一条、7 行的索引 + 2–3 局的正文
总量很小，工具环的复杂度（多一格图 + 一层协议 + 延迟）现在换不到收益。
它的收益随 run 变长线性增长——留到局数上百时再上。

### 3.4 一个必须先修的排序洞

`query_episode_summaries` 0914 改成"按 `episode_id` 字典序落定顺序"（因为
`MemoryStore.filter` 的交集走 `set`，本身无序）。但 `episode_id` 是
`{run_id}-ep{n}`（`dispatch.py:55`）——**字典序在 `n >= 10` 时会乱**（`ep10 < ep2`）。
plan 的索引行是"按执行顺序"读的，这个洞会让第 10 局之后的历史顺序错位。

修法二选一：① 索引行按 `episode_id` 的**数值尾号**排；② 用 `state.outcomes` 的顺序
（它是执行序 append 的机械记录，本来就准）作为排序键。
**②更稳**——不必从字符串里反解执行序。

### 3.5 落点

| 文件 | 改成 |
|---|---|
| `harness/run/nodes/plan.py` | `events=deps.trace.read_events()` → `summaries=deps.memory.query_episode_summaries(conditions={"run_id": deps.run_id})` + 选题规则 |
| `schemas/harness/communication/PlanOnceReq.py` | `events: list[TraceEvent]` → `index: list[EpisodeMemory]` + `details: list[EpisodeMemory]` + `object_facts: list[ObjectEvent]`（§6-3 定的那一面） |
| `tools/prompts/run_plan.py` | `history_lines(events)` → `index_lines(summaries)` + `detail_blocks(chosen)` + `object_lines(events)` |
| `tools/prompts/calls/run_plan.md` | `$history` → `$index` + `$details` + `$objects`；删掉 LIFO 逆序那段（§2.3） |
| `tools/brain_tool.py::plan` | 只换渲染函数的调用，`Brain.plan(history=…)` 传的是"索引行 + 详情块 + 地图事实"拼起来的序列 |
| `tools/interface/ports.py` + `memory_tool.py` | `query_object_events` 的 `map_id` 由必填 `int` 改成可选条件（§6-3） |

**`docstring` 与注释要同步改**：`plan.py` 模块 docstring 里"读历史的口径不在本文件
…把磁盘账本的全量快照塞进 `PlanOnceReq.events`"（`plan.py:22-27`）这段整段作废；
`PlanOnceReq` 的 `events` 字段说明（含 `RUN_TRACE_MASK` 的历史沿革）整段作废。
**留着不改就是在教人用一个不存在的东西。**

### 3.6 语义抽取（依赖项，独立收益）

索引与详情解决的是"**怎么读**"；还有一件"**有没有得读**"的事——episode 收尾只产
"一局的摘要"，不产"这一局新增的世界事实"（0913 23:08 记录里那张对照表的空缺格）。
用户点名的四类原料（对话 / 战斗 / 招式 / 尝试）里，**对话与招式原先没有 memory 出口**。

它属于**写入侧**（收尾链多一格抽取 → 落 `knowledge_memory`），与 plan 的读侧改造**解耦**，
两者各自独立上线。**S4 已落地**（0914，`CHANGELOG.md` 第 82 条）：第 22 个节点
`harness/episode/close/extract_knowledge.py`，`Brain.extract()` 是大脑的第七条链路，
产物 `KnowledgeRecord` 只落 `knowledge_memory/`（**不落 `object_memory`**——
那一族是"哪一格里有什么"，由局内的 `store_object_semantic_memory` 按坐标写，
两族的定位不同，抽取不该跨界代笔）。

> ⏸ **已摘出运行路径**（0914 98）：用户定「knowledge 由人管理」——节点不进图、
> 账不再产出，`knowledge_memory/` 只剩人工先验。`extract_knowledge.py` /
> `Brain.extract()` / `prompts/calls/extract.md` / `store_knowledge` / 三个
> trace kind 都留在原位（接回三行 + 六个节点表 + 两条核对，见 `CHANGELOG.md`
> 第 98 条）。**下面这两条接口裁定仍然有效**——它们是接回去时必须满足的条件。

**接口的关键裁定**（都要在改这一段时一起读）：

- **素材必须已过校验**：路由在 `verify_and_summarize` 出口按 `verified_steps` 分叉，
  从没被核对过的自述里抽知识等于把幻觉固化成"世界规则"；
- **失败不让这一局失败**：知识是附加产物——`verify`/`summarize` 拿不到就没有这一局的
  记录本体，所以它们照旧上抛；抽取拿不到只少一条世界知识，下一局还会再读到。
  为它把整局翻成 `episode_error`，等于让一条锦上添花的链路有能力污染成功率。
  这是全项目唯一一处"重试耗尽不破坏外层"的调用点，而它**不吞**：两笔账照写，
  "抽取器坏了"与"这一局什么都没读到"在 trace 上分得开。


---

## 4. 两块设计的关系与边界

- **(b) 管 run 内进度**：任务表活在 `RunState` 里，随 run 结束而消失（checkpoint 恢复链
  已删，run state 不跨 run）。**任务表不跨 run**——下一个 run 的意图由 plan 重新生成。
- **(a) 管"本 run 内跨局"的回顾**：plan 读的是**本 run 早先那几局**的 `episode_memory`。
  **它不是"跨 run 的经历"**（0914 订正，见 §6）：一条 `episode_memory` 就是**那一局
  step 记忆的总结**（一局一条正文 + 一串来源章）——`run_id` 只决定它落在哪个批次，
  **不决定它是什么**。真正与 run 无关的是另两族：`knowledge`（世界规则——手写先验与
  run 学到的同族同形，见 S4）与 `object_fact`（锚在地图上的交互事实，按 `map_id` 存、
  刻意不按 `episode_id` 过滤）。
- **接缝是 `GoalEntry.last_episode_id`**：表上的"这一条我跑过一局" → 指针 → memory 里那一局详情。
- **失败在两处各留一份**，语义不同、都要：
  - 表上 `status=FAILED`（run 内的活跃状态，"这个目标我试过、跑挂了"）；
  - `episode_memory` 里一条失败局的记录（落进记忆库，本 run 后面按 `run_id` 读它就读得到）
    —— **S3 已补**：一条**只有来源章、正文为空**的记录（0914 99 起不再带
    `chapter_only` 标记，空不空看正文自己；仍属 `episode_memory` 一族，
    "可重建 / 可丢弃"两条推论对它照旧成立），
    写入点是 `review`（唯一每局必过的地方）。原先两处漏洞——`episode_error_handler`
    拿不到 runtime、`verify_and_summarize` 那支"没有任何可信 step 记忆"只写 trace
    不落 memory——都由这一条补章统一收口。


---

## 5. 实施顺序

> **五步全部落地**（S1 02:36–02:42，S2/S5 03:39–03:43，S3 08:32，S4 09:0x）。这一节
> 保留成"当时按什么顺序做、靠什么验证"的记录——**验证方式那一列值得复用**：
> 每一步都只用一个不碰真机、不调模型的小件就能证明自己。

| 步 | 内容 | 依赖 | 可独立验证 | 落地 |
|---|---|---|---|---|
| **S1** | 状态化任务表（§2 全部改动点） | — | `tests/test_run_graph_termination.py` | ✅ 第 76/77 条 |
| **S2** | plan 换读口（§3.1–3.2、3.4、3.5，含 docstring 清理）；`query_object_events` 的 `map_id` 改可选条件（§6-4）；`PlannerContext.events` → 索引 + 详情 | 无（S1 已完成） | 假 memory + 假 planner 跑节点，断材料与排序 | ✅ 第 79 条 |
| **S3** | 失败局的 memory 出口（§4 末、§6-3） | 无（可与 S2 并行） | 真 `MemoryTool` + `tmp_path`，断"一局一条" | ✅ 第 81 条 |
| **S4** | 语义抽取（§3.6） | S2 | 假 `BrainPort` + 真 `BrainTool`/`MemoryTool`，断落族与失败不带走这一局 | ✅ 第 82 条 |
| **S5** | `Planner` 的 `updates`（`abandon` / 重开，§2.2 末） | S2 | 跑 `plan` 节点，断"弃完最后一条 → 表末检成立" | ✅ 第 80 条 |
| — | **工具环（§3.3）** | S2 | —— | ⏳ 二期留缝 |


---

## 6. 决策记录（0914 03:2x 用户裁定）

> 这一节的条目**除第 6 条外全部已落地**（0914 09:0x）；落地形态见 §0 那张表。

### 已定（0914 03:2x 用户裁定）

1. **表序即优先级**（§2.3）——**接受**。LIFO 退役，第一个 `PENDING` 先做。**已落地。**
2. **状态写入权限**（§2.2）——**接受**。`COMPLETED`/`FAILED` 只能由 harness 从
   `outcome.success` 盖章，模型和人都不能直接写。**已落地**：`GoalStatus` 的类 docstring
   就是那张权限表；人推翻 judge 裁决走 `review.audit`，推翻之后仍由 harness 重新盖章。
3. **失败局进 `episode_memory`**（§4 末）——**收**。落一条只有来源章、正文为空的记录。
   **已落地（S3）**：正文全空的记录 + 写入点 `review._leave_chapter()`
   ——`review` 是**唯一每局必过**的地方，所以"每局恰好一条"只有这里有唯一收口。
4. **`object_memory` 进 plan 的检索面**（§3.5）——**进**。连带把 `query_object_events`
   的 `map_id` 从必填 `int` 改成**可选条件**：plan 是 run 级、没有当前观测也就没有地图。
   另一个走法（从本 run 的 `step_memory` 元数据里收集 `map_id` 再逐图查）**不选**——
   那是让消费方自己拼索引。**已落地（S2）。**

### 已定（0914 0x:xx）

5. **`abandon` 的机制**（§2.2 末）——**建**，按形状 (i)：`Planner` 的产出带一层
   `updates`，只允许 `PENDING` / `ABANDONED`。**已落地（S5）**：
   `PlannerOutcome.updates` + `ALLOWED_UPDATE_STATUSES`，`RunPlan.PlanUpdate` 用
   **表内序号**寻址（`task_id` 是 run 级标识符，不泄进 `brain`），
   越界那条只是作废。控制台语法：`@序号 放弃|重开 理由`。
6. **工具环**（§3.3）——**还没做**，二期的留缝：让模型自己请求"我要看哪几局的正文"，
   那时 `plan._pick_details` 退休（信封不用改）。等 S2 的实跑数据出来再定。


### 已订正

**"`episode_memory` 是跨 run 的"这句话是错的**（用户指出，0914）。准确说法：
**一整局 step 记忆的总结，一局一条**——`run_id` 只决定它落在哪个批次，不决定它是什么。
`EpisodeMemory` 的类 docstring 0913 起就是按这个写的，但仓里另有一批描述把它说成
"跨 run 的经验"，已按同一口径校正（`episode_memory.py` 模块说明、`memory_tool.py`
四类记忆表、`brain_port.summarize`、`SummarizeResult`、`BrainToolPort.summarize`、
`summarize.md`、`retrieve_global_episode_memory.py`、`ROADMAP` 第 27 条）。
