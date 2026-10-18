> R6c（529）清理说明：旧后端、控制台、网页与实时推送已删除；依赖旧后端信封的旧 AI 进程及其测试一并删除。R7 保留新 AI 席、依赖与探针工作。

# Reviewer spec —— 全链路只读透明 + 最终裁决（插话 / 审），一个独立 reviewer 进程、人（终端）与 AI 同权

> 流程位置：intent.md → **spec.md**（本文件）→ plan → 落码
> 状态：v3（2026-10-17）；R1a、R2、R3、R3b 已完成；其余待按 plan 逐步放行，**R3 起须等 brain-scope 合入主线后恢复**（见 plan §八）
> v3 修订原因：brain-scope（`docs/brain_scope/spec.md` v1.3）改变大脑请求的形状，并让规划 / 拆解处开始看图。本稿同步：①更正 #18 的前提并新增 #19–#21（`brain_input` 里的帧、`read_brain_frames`、AI 首条消息不带图）；②`ReviewContext` 渲染按新字段（4.1）；③`RecallQuery` 增 `run_goal` 键与 `runs` 提示；④清掉 v2 遗留的 `frame` 残句（6.5、7.2、十四、十五）与 `FrameQuery` 缺 `latest` 的不一致。
> v3.1（2026-10-17）：task 层改为**可选审点**（配置 `REVIEW_LAYERS`，默认关闭，只做 judge 处的 audit，不做 inject），见 #22；新增 R3b。
> v4（2026-10-17）：reviewer 改为**独立进程**（人、AI、hub、读端口同在其内，harness 只经 `Reviewer` 端口与薄适配 `RemoteReviewer` 相连），见 #23；删除 harness 侧 `ReviewView`；`read_world` 取消；重写 §二 / §五 / §六 / §九 / §十 / §十三，R5 / R6 重排。
> 上游：`docs/reviewer/intent.md`
> 改动面：`harness/`、`schemas/`、新包 `reviewer/`（独立进程）、新包 `reviewer_link/`（run 侧适配）、`build.py` 一处装配；旧的 `review_backend/`、`agent_reviewer/` 已在 R6c 删除
> 约束：不碰 brain；不改 `Reviewer` 协议的两个方法名；产出只有一个作者（无改写）；harness 只依赖自己定义的端口

---

## 〇、相对现状的更正（均核过代码）

| # | 现状 | 本 spec 的处理 |
|---|---|---|
| 1 | 审点共四处：两层 `_settle`（审 task / 审 episode 的机械结算）+ 两层 `audit_judgement`（审 judge「已达成」） | **只留后两处**（R1a 已完成）；`_settle` 里的 `ask_audit` 及其推翻分支删除 |
| 2 | `FromHarnessToReviewerAuditReq.outcome` 是 `EpisodeOutput \| TaskOutput \| JudgeResp` 三选一 | 收窄为 `JudgeResp`（R1a 已完成） |
| 3 | reviewer 只看到「这一问」 | 每问带一份**快照** `ReviewContext`，并可经 由人 / AI 经 reviewer 进程自己的**只读读端口**查询 trace、记忆与历史画面（人、AI 同权；v4 起不含世界查询，#23） |
| 4 | 回话只有 `answered: bool` | 增 `by: human \| agent \| none`；`answered == (by != "none")`（R2 已完成） |
| 5 | `plan_run` / `plan_episode` 的 `while True` 重问循环无上限 | 对 **`by == "agent"` 的连续插话**设上限（人不设限），到顶接受当前版并记 `capped` |
| 6 | AI 席：零工具、无结构化输出，`_parse` 用关键词子串判认账 / 推翻 | 改为**原生 function calling 的有界工具循环**，循环引擎用 Pydantic AI（结论是输出类型对应的 `final_result` 工具调用） |
| 7 | AI 提案的插话恒空 | 放开；由 #5 的上限兜底 |
| 8 | 旧设计：后端 `_serve_harness` 读写分离、harness ⇄ 后端 WebSocket（跳 A）、`view_query` 跨进程转发 | **作废**：后端并入 reviewer 对象（#14），查询是进程内函数调用 |
| 9 | 设计初稿里「人席只看快照、不能查询」 | **人席与 AI 席对称**：同一份快照、同一个 `ViewQuery`、同样的两种权力 |
| 10 | 旧 spec：`ReviewContext.tasks: list[GoalEntry]`，且两层都带 `goals` | `tasks` 的元素类型是 **`TaskEntry`**；`goals` 只有 run 层有、`tasks` 只有 episode 层有（`EpisodeRunState` 没有 run 目标表）；模型带互斥校验 |
| 11 | 旧 spec：「同一信息不两处传」未落到实处 | 落在**渲染层**：大脑请求里的表（`plan` / `task_table`）与 `goals` / `tasks` 是同一张表，对象里保留两处，渲染文本只出一份 |
| 12 | 旧实现：reviewer 的画面来自后端缓存里**实时流 `/feed` 的最新一帧**（`_latest_frame`），不一定是大脑看到的那一帧 | 画面**按需拉取**：提问时刻的画面走 `read_frame` 的 `latest`（取自 trace），大脑这一问看到的图走 `read_brain_frames`（#19），历史画面走 `read_frame`；reviewer 与实时流彻底无关。取法见 #18 / #19 |
| 13 | `/feed`、`LiveFeedTrace`、`live_feed_url`、两个 Feed 信封 | **移出 reviewer 子系统并删除**（R6c），实时展示将另立项目，从 git 历史取回 |
| 14 | 三个进程：run、后端、agent_reviewer | 合并为**一个 reviewer**：编排模块（原后端逻辑）与席位模块（人、AI）同在其内；**v4（#23）：reviewer 单独成进程**，harness 只依赖 `Reviewer` 端口，run 侧只有薄适配器 `RemoteReviewer` |
| 15 | 人的入口：控制台（stdin 一行）与网页 | **只做终端**：reviewer 进程自带的命令行（v4：不再是连别人端口的独立客户端）；网页前端暂不做；`ConsoleReviewer` 由它取代 |
| 16 | 旧 spec：`_MemoryReader` 有「按 (episode_id, step) 取帧的只读查询」 | 代码里**不存在**：`MemoryToolPort` 只有 recall / memorize / snapshot / restore，MCP 面默认只暴露 recall / memorize（2026-09-29 定案，运维口仅 `--enable-admin`）。`read_frame` 先经 `recall(conditions={episode_id})` 取 act 族条目再按 step 挑帧，**可行性在 R5 前置核查** |
| 17 | 倒计时在网页里（页面从首个 proposal 起算、归零自动提交） | 倒计时**移入编排模块**：CLI 与（将来的）任何入口行为一致，纯 AI 模式不需要任何界面 |
| 18 | 旧 spec（v2 初稿）：`ReviewContext.frame` 取自 `state.observation` / `state.ep_ctx.observation` 的画面编码，每问预先带 | 两点都改：①`Observation` 没有画面字段（R3 执行方停止汇报、设计侧核实）；画面只在两层 `sense` 追加的 `sense_frame` 账的 `content.frame`里（完整 data URI）。②更关键（**此前提已被 #19 更正**：brain-scope 之后规划 / 拆解处看图）：**大脑在规划与拆解处根本不看图**（`PlanOnceReq` 无 images；`DecomposeReq.observation` 是文字化观测），判定看的图是 `req.history` 里的历史前后帧而非当前帧。故「当前帧」不是任何 reviewer 介入点的大脑输入，**不进 `ReviewContext`**；画面一律按需拉取：`FrameQuery` 增 `latest`（读 trace 里最近一条 `sense_frame` 的 `content.frame`）与按 (episode, step) 取历史帧两种，在 R5 实现。R3 不带画面、不碰 trace 读取。另：`schemas/harness/domain/trace_event.py` docstring 里「`frame_png` 删除」只指顶层字段，易误读为事件里没有画面，R11 订正 |

| 19 | v2 的 #18 把「规划与拆解处大脑不看图」当前提（`PlanOnceReq` 无 images）。brain-scope（spec v1.3 D9，CP4）之后该前提**不再成立**：`BrainPort.plan` / `decompose` 增 `images`，L0 带每局首末帧、L1 带每 task 首末帧；这些帧就在请求里的记忆对象上（`EpisodeMemory` / `TaskMemory` 的 `first_frame` / `last_frame`）。reviewer 默认只涉及 run / episode 两层，即这两类对象（task 层可选，其帧在 `ActMemory` 的前后帧上，同理，见 #22） | #18 的**结论不变**：「当前帧」仍不是任何请求的入参，仍不进 `ReviewContext`、仍按需拉取。**新增一条口径**：reviewer 必须能看到「大脑这一问看到的图」。`brain_input` 的记忆对象本来就带着帧，由纯函数 `frames_of(brain_input)` 取出（顺序与去重同大脑；不套 `SCOPE_IMAGE_CAP`，故 reviewer 可见 ⊇ 大脑所见）；新增查询变体 `BrainFramesQuery`（`read_brain_frames`），分页返回，由 hub 用当前问的快照回答（5.3）。渲染文本一律不输出这些 data URI，只写「图 N 张」 |
| 20 | v2 的 7.2 写 AI 首条消息带 `context.frame` 图 | 作废（该字段自 #18 起已不存在）：**首条消息只带快照文本，不带图**；图由 AI 按需调 `read_brain_frames` / `read_frame`。理由：brain-scope 后一问的大脑图像最多 20 张（`SCOPE_IMAGE_CAP`），每问都带会把 AI 席成本推高一个量级，而多数问不需要看图 |
| 21 | v2 遗留：`FromReviewerToCliAskMsg.frame`、`test_four_review_points_carry_context` 与验收 4 里的 `frame`；`FrameQuery` 没有 #18 说的 `latest` | 一并订正：Ask 信封的 `context` 改为渲染文本，另带 `brain_frames`（张数），帧不上线（6.5）；`FrameQuery` 的 `which` 增 `latest`（5.2） |
| 22 | 原设计：reviewer 只管 run / episode 两层，task 层不碰 reviewer | 改为 **task 层可选**：配置 `REVIEW_LAYERS`（默认 `("run", "episode")`，加 `"task"` 即开）。开启后 task 层只多**一个审点**：`judge·L2` 判「已达成」时的 **audit**（与另两层同构：认账才盖 `GOAL_DONE`，推翻写 `TaskState.last_judge`、本 task 继续，下一次 choose 的 `human_note` 带推翻理由）。**不做 inject**：task 层的规划是逐步的 `choose`（一个 task 至多 12 步），逐步插话会让 run 被反复阻塞，且 `ChooseOnceReq.human_note` 已是现成的人工入口，需要时另案。默认关闭时 task 图行为与现状逐位相同；开启后每个 task 判成时阻塞一次（每 episode 至多 `episode_max_tasks` 次） |
| 23 | v3 及之前：reviewer 并入 run 进程（AI 席进程内线程，人经本地 WS 连独立 CLI 终端）；harness 里有 `ReviewView` 端口、`HarnessReviewView`、`ViewAware`、`bind_view` | **v4：reviewer 整体独立成进程**（用户 2026-10-17）。人席（终端）、AI 席（Pydantic AI，asyncio 任务）、hub、读端口同在一个进程；harness 只有薄适配 `RemoteReviewer`（`reviewer_link/`，经本地 WS 送出一问、等回话）。reviewer 自己持有 trace 与记忆的**只读**读端口，按需拉取；默认快照仍是 judge / plan 当次的请求。连带变化：①删除 harness 侧 `ReviewView` / `HarnessReviewView` / `ViewAware` / `bind_view`；②`read_world` 取消（快照已含 RAM 现状 `observation`；动作空间如需，由 run 随问附带）；③提问前 harness 先 flush trace，保证另一进程读到最新账；④查询模型的产出方改为 reviewer（`schemas/reviewer/`）；⑤`review_cli` 包不再有，终端并入 `reviewer`；⑥多终端同连取消；⑦往期问答可跨 run 保留（reviewer 进程不随 run 生灭，`HISTORY_LIMIT` 仍封顶）；⑧启动顺序：先起 reviewer、再起 run |

**术语**：intent 里「decode」＝ `plan_episode` 里的 **decompose**（把目标拆成 task）。

---

## 一、一句话结论

**reviewer 看到的 = 大脑看到的 + 全链路只读查询，且由人或 AI 自己去拉。** 每问随带一份快照（当次 plan / judge 的大脑请求原样 + 表 + 计数），trace、记忆、历史画面都不预先推送，由人（终端命令）或 AI（工具调用）按需读取。
reviewer 是**一个独立进程**：hub、人的终端、AI 席（Pydantic AI）与只读读端口都在里面；harness 进程里只有一个薄的 `RemoteReviewer`，实现现有的 `Reviewer` 端口，经本地 WS 把一问送出去、等回话。
reviewer 的两种权力不变：插话（让 LLM 重做）、审（认 / 推翻）。

---

## 二、拓扑与数据流

```
run 进程                                       reviewer 进程  python -m pokemon_agent.reviewer
┌──────────────────────────────┐              ┌──────────────────────────────────────────────┐
│ harness 图线程                │   本地 WS     │ hub：挂起一问、仲裁、倒计时、历史、命令层          │
│  plan_* / review_and_judge   │ ask ───────► │   ▲ typed API                ▲                 │
│   └─ RemoteReviewer          │ ◄─────────── │   │                          │                 │
│      flush trace 后发出、     │   answer     │ 人席（终端）              AI 席（Pydantic AI 任务）│
│      阻塞等回话               │              │   └────── ViewReaders（只读）──────┘           │
└──────────────┬───────────────┘              └──────────────┬─────────────────┬───────────────┘
               │ 写                                            │ 读              │ 读
               ▼                                               ▼                 ▼
        trace 存储（文件 / Langfuse）  ◄───────────────────────┘        记忆 MCP 服务 ◄┘
```

要点：
1. **进程边界在 `Reviewer` 端口上。** harness 只依赖自己定义的 `Reviewer` 端口；run 侧实现是 `RemoteReviewer`（`reviewer_link/` 适配层），把一问序列化后经本地 WS 送出，阻塞等回话。
2. **提问前先 flush trace；阻塞期间 run 静止。** 所以 reviewer 进程读到的 trace 与记忆是一致、最新的。
3. **查询是 reviewer 进程内的函数调用**：人经命令层、AI 经工具循环，最终都调同一个 `ViewReaders` 实例；读的是共享存储（trace 存储、记忆 MCP 服务），不经 harness。
4. **依赖方向**：`reviewer` 包除装配入口 `__main__` 外只引 `schemas` 与第三方库；`__main__` 用现有 `trace` / `mcpclient` 的构造器造两个只读读端口。harness 不 import `reviewer`；`reviewer` 不 import harness、brain、world。
5. **人与 AI 同权**：同一份快照、同一个 `ViewQuery`、同样的回话类型；差别只在入口与两道安全阀（见 7.5）。
6. **范围是只读的全部可见面**：trace（默认本 run，可指定其他 run）、记忆、历史画面、往期问答。没有世界查询（#23）。边界是「任何查询都不能产生写」：读端口是窄 Protocol，没有写方法。
7. **启动顺序**：先起 reviewer，再起 run；一个 reviewer 进程可先后服务多个 run（同一时刻一个）。

---

## 三、审点收敛（harness 侧改动）

### 3.1 已完成（R1a，提交 cb58459）

两层 `_settle` 不再问 reviewer；`ask_audit` 并入 `audit_judgement`；`AuditReq.outcome` 收窄为 judge 裁决；`task_id` 从审的信封与跳 A / 跳 B / 页面删除；`review_render` 与控制台的结算审分支删除。`state_schema_hash()` 前后相同（`40e2cd635256744f`）。

### 3.2 保留（行为不变）

- episode 层 `_settle` 里**与审无关**的逻辑原样保留：`INTERRUPTED` 的 note、失败定案后把剩余 `PENDING` 标 `ABANDONED`、`SETTLE_TASK` 账的 `abandoned` / `fail_streak`。
- `audit_judgement`：只在 judge 判「已达成」时审；`feedback.audit is ACCEPT` 才盖 `GOAL_DONE`；推翻写 `last_judge`，下一轮 plan 看得见。
- 两层 `plan_*` 的插话点与「带着 `human_note` 重问」。
- 没人答 = 认账 / 无意见。

### 3.3 后果（须知悉）

task / episode 的**成败从此只由机械判定决定**，不再有人审翻转（开启 task 层后，task 的成败在 judge 判成处多一道 audit，推翻只让本 task 继续，机械结算的其余部分不变，#22）。reviewer 能影响它的唯一途径是 judge 处推翻 / 插话让 plan 重做。
`CLAUDE.md` / `AGENTS.md` §四第 3 条写的「人审推翻只改目标表 / 任务表（`overturned`），定案以表为准」随之失效：
推翻只剩 judge 处这一种，且只写 `last_judge`。该段文字在 R9 同步修订（改规范先讨论——这是需要你点头的一处）。

### 3.3a 删 `overturned` 字段的连带代价（决定拆成 R1a / R1b）

`harness/checkpoint/manifest.py::state_schema_hash()` 是 `RunState` / `EpisodeRunState` / `TaskState` 三个模型 JSON Schema 的哈希；
`restore.py` 在哈希不同时**拒载**存档。`GoalEntry.overturned`、`TaskEntry.overturned` 在这三个状态模型里，
所以**删除这两个字段会改变哈希，使所有既有存档拒载**——包括 `evals/agent_short_goal_run/dataset/v1/archives/` 下 20 份 manifest 对应的存档，以及用户自己的 `checkpoints/`。上一次重建见 CHANGELOG 441（需要真实模拟器与用户授权）。

- **R1a**（已完成）：只做审点收敛与「写 True」路径删除；字段与全部读方保留；`state_schema_hash()` 逐位相同。
- **R1b**（单独一步，须用户另行授权）：删字段 + 读方 + 重建 20 份评测存档；等改这 20 份 manifest 的评测任务合入后再做，**且排在 brain-scope 的 CP8 重打之后**（两者都改 `state_schema_hash()`；次序与是否合并成一次重打见 plan §八）。
- R1a 期间 `overturned` 恒为 `False`，是**有记录的临时死代码**，由 R1b 清除，不留兼容壳到 R11。
- 结算账 `SETTLE_GOAL` / `SETTLE_TASK` 的 `audit` 键：R1a 保持形状不变（传 `None`，渲染 `req.audit or ""`）；去键并入 R1b，届时改 `parse.py` / `langfuse_trace.py` / `budget_record.py` / `settle_task_error.py`。

### 3.4 死代码清理（本 spec 的一部分，不是顺手活）

**范围判据**：只清「本 spec 使之失效」的东西，加上下面逐项列出且已核实的陈旧项；**不扩大到无关的历史遗留**。
**做法**：每项先 `grep` 读方，读方清零才删；清理与引起它的那一步**同提交**，不攒到最后。

| 类 | 清理项 | 随哪一步 |
|---|---|---|
| 推翻语义 | `GoalEntry.overturned`、`TaskEntry.overturned`；`entry_status.py` 文档表里两行「人审推翻」；`_stamp` 与 episode `_settle` 里的 `"overturned": False` | **R1b** |
| 推翻的读方 | `direct/prompts/decompose.py`、`direct/prompts/run_plan.py` 里「（人审推翻）」标记；`direct/trace/content.py`、`direct/trace/render.py` 的 `overturned`；`FromHarnessToBrainToolPlanOnceReq` docstring | **R1b** |
| 结算账 | `SETTLE_GOAL` / `SETTLE_TASK` 账里的 `audit` 键（`FromHarnessToTraceToolAppendReq.audit` 另被 judge 审账使用，**字段保留**） | R1b |
| 旧回话字段 | R2 加在跳 A `FromHarnessToReviewBackendInjectResp` / `AuditResp` 上的 `by`（随跳 A 整体删除） | R6c |
| 旧控制台 | `harness/console_reviewer.py::ConsoleReviewer`、`config.CONSOLE_REVIEW_TIMEOUT`；`tests/harness/review/test_reviewer_by.py` 里对它的用例（改为对 `ReviewerApp` / `RemoteReviewer`）；`docs/PLAN_console_reviewer.md` 的状态说明 | R6c |
| 旧网页与后端 | `harness/web_reviewer.py::WebReviewer`；整个 `review_backend/` 包（含 `page.py`、`agent_client.py`、`backend.py`）；`config.WEB_REVIEW_TIMEOUT`；跳 A（`FromHarnessToReviewBackend*`）与跳 B（`FromReviewBackendToFrontend*`、`FromFrontendToReviewBackend*`）全部信封及其包出口；对应测试与夹具 | R6c |
| 实时流 | `direct/trace/live_feed.py::LiveFeedTrace`；`TraceTool.build` 与 `build.py` 的 `live_feed_url` 参数；`FromHarnessToReviewBackendFeedReq` / `FromReviewBackendToFrontendFeedReq`；`tests/_harness_fixtures/harness.py` 的 `live_feed_url`；相关测试 | R6c |
| 旧 AI 席 | 整个 `agent_reviewer/` 包（`agent.py` 的 `_OVERTURN_WORDS` / `_ACCEPT_WORDS` / `_parse` / `_render`、`server.py`、`provider.py` 旧形状）；`schemas/agent_reviewer/`；对应测试 | R6c（关联清理） |
| 线上陈旧字段 | 随跳 A 一并消失（`timeout_s` 等） | R6c |
| 文档与测试 | `reviewer.py` 顶部「落点」表；`docs/agent_reviewer/card.md`、`docs/agent_reviewer/spec.md`、`docs/web_reviewer/*`（加状态说明，正文不改）；测试里对 `overturned` / task 审点的断言与假件 | R6c / R7 / R9 |
| 规范 | `CLAUDE.md` / `AGENTS.md` §四第 3 条中「人审推翻只改目标表 / 任务表」整句（须你点头） | R9 |

收尾自查（R11）：`grep -rn "overturned" pokemon_agent tests` 与 `grep -rn "ask_audit\|_OVERTURN_WORDS\|LiveFeed\|review_backend\|agent_reviewer\|WebReviewer\|ConsoleReviewer"` 无残留。

---

## 四、`ReviewContext`：随问快照

**归属**：harness 产出 → `schemas/harness/domain/review_context.py`（裸名）。

```python
class ReviewContext(BaseModel):
    layer: Literal["run", "episode", "task"]   # task 为可选层（#22）
    run_id: str
    episode_id: str                      # run 层放 run_id（与现有 meta 约定一致）
    task_id: str | None = None           # 仅 task 层有
    brain_input: PlanOnceReq | DecomposeReq | JudgeReq
        # 产出本次表单 / 裁决的那封大脑请求原样放进来 = "大脑看到的"
        # （FromHarnessToBrainToolPlanOnceReq / DecomposeReq / JudgeReq）
        # 请求里的记忆对象保留其帧字段（进程内类型，不拷贝、不剥帧）；字段形状随 brain-scope 变化，见 4.1
    goals: list[GoalEntry] | None        # 仅 run 层有；episode 层为 None
    tasks: list[TaskEntry] | None        # 仅 episode 层有；run 层为 None
    step: int                            # 本层账面步号（调用点 meta["step"]）
    fail_streak: int
```

- **互斥校验**：`layer == "run"` ⇒ `goals` 非 None 且 `tasks` 为 None；`layer == "episode"` ⇒ `tasks` 非 None 且 `goals` 为 None；`layer == "task"` ⇒ `goals`、`tasks` 皆 None 且 `task_id` 非 None（task 层的快照就是 `brain_input` 里的 `JudgeReq`：task 目标、本 task 全部 ActMemory、`task_index`、`knowledge`）（用仓库既有的契约写法）。task 层的 fail_streak 取本层 stall_count。
- **取值**：run 层 `goals` 取判停前已定案的表（`updates.get("goals", state.goals)`）；episode 层 `tasks` 取 `updates.get("tasks", state.tasks)`；`brain_input` 取该次实际发给大脑的那封请求；
  不放「当前帧」（更正 #18）；大脑这一问看到的图在 `brain_input` 的记忆对象里，经 `frames_of` 取、经 `read_brain_frames` 按需看（更正 #19）。
- **不放**：世界动作空间（不是任何一次大脑请求的入参；v4 起 reviewer 没有世界读取，#23）。
- **构造者**：四个调用点（`plan_run` / `plan_episode` / 两层 `review_and_judge`）各自在已有变量上拼，不新增读取；开启 task 层时再加 task 层 `review_and_judge` 一处（R3b）。
- **渲染**：`review_render.render_context(ctx) -> str`，复用 `format_form`，输出分节文本
  （`## 大脑输入` / `## 目标表` / `## 任务表` / `## 计数`）。要求：
  1. 文本不含 `data:image` 或 base64：`brain_input` 里记忆对象的首末帧（`first_frame` / `last_frame`）一律不输出，该处只写「（图 N 张，用 `brain-frames` 查看）」；验收口径是文本里不含 `data:image`；帧不进文本，也不上线（6.5）；
  2. 渲染 `brain_input` 时跳过 `PlanOnceReq.plan`、`DecomposeReq.task_table`、`JudgeReq.task_table`，表由 `## 目标表` / `## 任务表` 节统一展示；也不重复渲染 `InjectReq.form`（同一信息不两处传）。brain-scope 之后 `PlanOnceReq.index` 已删除，无需处理；L0 判停的 `episode_memories` 与 plan·L0 的 `details` 是同一份对象，但分属两问，各自完整渲染。
- **进入请求**：`FromHarnessToReviewerInjectReq` 与 `FromHarnessToReviewerAuditReq` 各增必填字段 `context: ReviewContext`；经链路时整体序列化（含记忆对象里的帧，见 6.5）。

### 4.1 `brain_input` 的形状（依 brain-scope spec v1.3 第一节；字段名以其落码为准，R3 开工时重核）

默认只涉及 run / episode 两层（task 层可选，见 #22），下表为这两层与可选的 task 层的形状：

| 调用点 | 请求 | 详情（全文渲染，与大脑所见一致） | 索引（一行一条） | 其他 | 带帧的字段 |
|---|---|---|---|---|---|
| `plan_run`（plan·L0） | `PlanOnceReq` | `details`：本 run 全部 EpisodeMemory | `run_index` | `knowledge`、`observation`；`index` 已删；`plan` 渲染时跳过 | `details[*].first_frame` / `last_frame` |
| run 层 judge（judge·L0） | `JudgeReq` | `episode_memories`（与 plan·L0 的 `details` 同一份） | `run_index` | `knowledge`、`observation` | 同上 |
| `plan_episode`（plan·L1） | `DecomposeReq` | `task_memories`：本 episode 全部 TaskMemory | `episode_index`（原 `episode_memories` 改名） | `task_table` 渲染时跳过 | `task_memories[*].first_frame` / `last_frame` |
| episode 层 judge（judge·L1） | `JudgeReq` | `task_memories`（同一份） | `episode_index` | `knowledge`、`observation` | 同上 |
| task 层 judge（judge·L2，**可选**） | `JudgeReq` | `history`：本 task 全部 ActMemory | `task_index` | `knowledge`；RAM 现状由 `history` 最后一条的 `after` 给出 | `history[*].before_frame` / `after_frame` |

- 体量变大：L0 详情是最多 `max_episodes`（brain-scope 后默认 10）条局记忆全文，`ctx` 因此改为**按节输出**（`ctx [--section 名]`，6.4），默认只打节目录与各节行数；AI 首条消息仍是全文（与大脑所见等量），故不带图（#20）。
- 渲染对索引行直接用对象自带的 `index_line()` 结果，不另写一套。

---

## 五、`ViewReaders`：只读查询（reviewer 进程内）

### 5.1 读端口与门面（`reviewer/view/`）

```python
class TraceReader(Protocol):          # 对应 TraceToolPort.read_events，仅此一个方法
    def read_events(self, meta: dict) -> list[TraceEvent]: ...

class MemoryReader(Protocol):         # 对应 MemoryToolPort.recall，仅此一个方法
    def recall(self, req: FromHarnessToMemoryToolRecallReq) -> FromHarnessToMemoryToolRecallResp: ...

class ViewReaders:
    def __init__(self, trace: TraceReader | None, memory: MemoryReader | None,
                 *, trace_delayed: bool = False) -> None: ...
    def read_trace(self, q: TraceQuery, *, default_run_id: str) -> ViewAnswer: ...
    def recall(self, q: RecallQuery) -> ViewAnswer: ...
    def read_frame(self, q: FrameQuery, *, default_run_id: str) -> ViewAnswer: ...
```

签名以 R5 核查结果为准。`read_brain_frames` 由 hub 回答（5.3）。同步端口在 hub 的单事件循环里经 `run_in_executor` 调用，不阻塞终端与倒计时。

返回 `ViewAnswer(ok: bool, text: str, images: list[str])`：`text` 是渲染好的文本（人 / LLM 直接读），`images` 只有 `read_frame` / `read_brain_frames` 才非空（data URI，单次 ≤ `FRAME_QUERY_MAX_IMAGES`）。预期读取失败 `ok=False` 并在 `text` 里说明；编程错误上抛。

### 5.2 查询模型（`schemas/reviewer/view.py`，reviewer 产出）

```python
class TraceQuery(BaseModel):
    tool: Literal["read_trace"] = "read_trace"
    run_id: str | None = None          # None = 当前问所属的 run；给定则只读那个 run 的账
    episode_id: str | None = None
    task_id: str | None = None
    source: str | None = None
    kind: str | None = None            # TraceKind 的值
    last_n: int = Field(default=20, ge=1, le=TRACE_QUERY_MAX_ROWS)
    offset: int = Field(default=0, ge=0)   # 从最新往回数
    content_limit: int = Field(default=300, ge=0, le=TRACE_QUERY_MAX_CONTENT)

class RecallQuery(BaseModel):
    tool: Literal["recall"] = "recall"
    query: str = ""
    conditions: dict[str, str] = {}    # 仅允许 episode_id / map_id / place / run_id / run_goal 五个键，外加提示 runs=all（列出全部 run 级记忆，不与其他键组合）；校验器拒其他键
    limit: int = Field(default=8, ge=1, le=RECALL_QUERY_MAX_ROWS)

class FrameQuery(BaseModel):
    tool: Literal["read_frame"] = "read_frame"
    episode_id: str | None = None      # which == "latest" 时必须为 None
    step: int | None = Field(default=None, ge=0)   # 同上
    which: Literal["before", "after", "latest"] = "after"
        # latest = 读 trace 里最近一条 sense_frame 账的 content.frame（更正 #18）
        # 校验：latest ⇒ episode_id、step 皆 None；before / after ⇒ 两者皆必填

class BrainFramesQuery(BaseModel):          # 更正 #19：本问大脑看到的图，分页
    tool: Literal["read_brain_frames"] = "read_brain_frames"
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=FRAME_QUERY_MAX_IMAGES, ge=1, le=FRAME_QUERY_MAX_IMAGES)

ViewQuery = Annotated[
    TraceQuery | RecallQuery | FrameQuery | BrainFramesQuery, Field(discriminator="tool")
]
```

`TRACE_QUERY_MAX_ROWS=50`、`TRACE_QUERY_MAX_CONTENT=2000`、`RECALL_QUERY_MAX_ROWS=8`、`FRAME_QUERY_MAX_IMAGES=2` 属于**模块私有物理量**，放在该模型文件里，不进 `config.py`。这些上限约束的是单次返回给 LLM 的体量（上下文保护），不是访问范围。

`ViewQuery` 是检索接口的**唯一注册表**：加一种检索 = 加一个变体 + `ViewReaders`（或 hub）里加一个分支 + 测试；命令行子命令、`help`、AI 的工具 schema 全部由该联合类型派生，不另写。

### 5.3 实现

- **装配与只读**：`ViewReaders` 由 reviewer 的 `__main__` 装配；窄 Protocol 声明在 `reviewer/view/` 内，类型上拿不到 `append` / `memorize` 等写方法。记忆读端口背后是 MCP 客户端（`MCP_MEMORY_SERVER_URL`）；trace 读端口背后是与 run 同一后端、同一份配置的读取器。只用默认开放的 `recall`，不依赖 `--enable-admin`。
- `read_trace`：`meta = {"run_id": query.run_id or default_run_id, **非空过滤键}` → `read_events` → 按 kind 筛选 → 按当前事件契约 `(ended_at, seq)` 取尾部 `last_n` 并应用 `offset`，页内升序 → 复用 `render_events` 的行格式而不 import harness；正文先递归去图再按 `content_limit` 截断，0 表示不展示正文；**帧 / data URI 一律剔除**（只留 `[frame omitted]`）。Langfuse 装配传 `trace_delayed=True`，头行提示「可能不含最近几秒」。
- `recall`：`FromHarnessToMemoryToolRecallReq(query, conditions, limit)` → 文本化。**不强加 `run_id`**：记忆库跨 run 共享，大脑自己召回的索引就来自其他 run，reviewer 要看到「大脑看到的」就必须能查到同一批。
- `read_frame`：`which == "latest"` 读当前 run 最近一条 `sense_frame` 账的 `content.frame`；最新条目缺帧或格式坏时失败，不冒充返回更早画面。`before` / `after` 经 `recall(conditions={"episode_id": …}, limit=None)` 取该局 act 族完整 payload，按 `step` 精确匹配，返回 `images=[data URI]`；取不到或帧无效回 `ok=False`。R5 已经真实 MCP 服务端路径验证 12 条记录两帧完整保留、admin 关闭时可用，传输使用内存连接；不新增记忆能力。
- `read_brain_frames`（更正 #19）：**不经读端口**（读端口与「哪一问」无关），由 hub 用当前 pending 问的 `ReviewContext` 回答：`frames_of(ctx.brain_input)` → 按 `offset` / `limit` 切片 → `ViewAnswer(text=头行「共 N 张，本次第 i–j 张」+ 每张的来源标签（如 `r1-ep2 首帧`）, images=[…])`。`frames_of` 是 `schemas/harness/domain/review_context.py` 里的纯函数：按请求类型逐个取记忆对象的首末帧（task 层 `JudgeReq`：`history` 里每条 ActMemory 的前后帧），保持对象顺序，按帧字符串相等去重（同大脑），缺帧跳过，返回 `list[tuple[label, data_uri]]`；不套 `SCOPE_IMAGE_CAP`。该问已了结后回 `ok=False`（同其他查询）。
- **后置条件**：查询不写 trace、不改写记忆记录正文，不调用 memorize；读端口无业务写方法。R5 核查发现 recall 会刷新索引与向量 sidecar，用户明确允许此类客观更新，故复用现有 recall，不承诺磁盘零写入。reviewer 进程不构造 game / brain 端口。

### 5.4 装配

- `reviewer/__main__.py` 是 reviewer 进程的唯一装配点：读 `config.py` / `.env` → 造 trace 读端口与记忆 MCP 客户端 → `ViewReaders` → `ReviewerApp`。trace 或记忆缺配置时，对应查询回 `ok=False, text="读端口未接入"`，不阻止 reviewer 启动。
- harness 侧没有任何查询相关装配；`build.py` 只负责 `RemoteReviewer`（6.2）。
- trace 读协议支持调用方指定的 run。Langfuse 实例绑定 `(run_id, branch)` 的 trace_id；R6b 入口跨 trace 分页解码，再按完整 meta 精确筛选，不能只修改 meta 后继续使用固定分支的实例。分页沿已有时间窗，SDK 契约测试覆盖跨 run / branch，真实服务尚未联调。

---

## 六、reviewer 进程：hub + 席位 + 读端口

### 6.1 目录

```
pokemon_agent/reviewer/                 reviewer 进程（python -m pokemon_agent.reviewer）
  __main__.py            唯一装配点：读配置，造读端口与 AI 席，启动 ReviewerApp
  app.py                 ReviewerApp：hub + 席位 + 链路服务端的组合
  hub/
    hub.py               挂起一问、编号、仲裁、倒计时、历史、活动
    commands.py          命令层：文本 → 类型化调用；help 由 ViewQuery schema 派生
  seats/
    human.py             终端：读行、打印、PNG 落盘
    ai/                  AI 席（见 §七）
  view/                  ViewReaders 与窄 Protocol（见 §五）
  link/server.py         本地 WS 服务（harness 连入）
pokemon_agent/reviewer_link/            run 侧适配层
  remote_reviewer.py     RemoteReviewer（实现 harness 的 Reviewer 端口）
pokemon_agent/schemas/reviewer/         本进程产出的模型（Ask、Proposal、Settle、HistoryEntry、ViewQuery…）
                                        与 reviewer → harness 的线上信封
```

依赖规则：`reviewer` 包除 `__main__` 外只引用 `schemas` 与第三方库（`seats/ai` 另可引 `pydantic-ai-slim[openai]`，其余目录不可）；`__main__` 可引 `trace` / `mcpclient` 的构造器，**不引 harness、brain、world**；`reviewer_link` 只引 `schemas` 与 WS 客户端库、不引 `reviewer`。以导入扫描测试固化。

### 6.2 对外接口

```python
# reviewer 进程
class ReviewSeats(BaseModel):
    human: bool
    ai: bool                        # 至少一个为 True（契约）

class ReviewerApp:
    def __init__(self, seats: ReviewSeats, *, hub: AppHub,
                 commands: CommandRunner, human: HumanTerminal) -> None: ...
    async def ask(self, req: ReviewRequest) -> Settle: ...
    async def serve(self) -> None: ...        # R6a 消费注入的终端行源；R6b 另装配链路服务
    def close(self) -> None: ...             # 幂等取消当前问，关闭不伪造认账

# run 进程（reviewer_link/）
class RemoteReviewer:                # 实现 Reviewer 端口
    def __init__(self, url: str, *, flush: Callable[[], None],
                 lost_timeout_s: float | None) -> None: ...  # 装配点传 config 的默认 120s
    def inject(self, req) -> FromHarnessToReviewerInjectResp: ...   # 阻塞图线程
    def audit(self, req) -> FromHarnessToReviewerAuditResp: ...
    def close(self) -> None: ...
```

- reviewer 进程：单个 asyncio 事件循环承载 hub、链路服务、终端、AI 任务，所有状态只在这一个循环里改，无锁。`seats` 在启动命令里显式指定（`--seats human|ai|both`），不靠「有没有人连着」推断。
- R6a 只启用 human 席，其他有效席位配置明确拒绝，待 R7 接入 AI；所有组件经窄 Protocol 注入，构造不读取全局 stdin、配置或网络。终端行源与输出函数由装配方提供。链路服务、CLI 入口与真实 stdin 适配由 R6b 加入。
- `RemoteReviewer`：内部一条后台线程跑 WS 客户端；`inject` / `audit` 先调 `flush()`（trace 落盘），再把 `ask` 交给后台线程，并用 `concurrent.futures.Future` 阻塞图线程。同一 `qid` 重复提问幂等。连上时收 reviewer 的 `hello`（含 `mode`）。
- **断线语义**：链路丢失或尚未连上时，`RemoteReviewer` 每 30s 记一条醒目日志并持续重连，重连后重发当前未答的 `ask`（reviewer 按 `qid` 去重，已答的直接回缓存的答案）。最近一次 `hello` 的 `mode == "ai"` 时，丢失超过 `REVIEW_LINK_LOST_TIMEOUT_S` 即按 `by="none"` 返回（插话没意见、审认账）；`human` / `both`，或从未连上过，则**无限等**。
- 装配：`build.py` 保留显式 reviewer 实例的优先级；无实例时按 `reviewer_url` 参数、同名 `REVIEW_LINK_URL` 环境变量、config.REVIEW_LINK_URL 选地址，注入 `trace.flush` 与 config.REVIEW_LINK_LOST_TIMEOUT_S。无地址保持 NullReviewer；RemoteReviewer 不反向 import config 或 reviewer 实现。
- `NullReviewer` 仍用于**无头**场景（没有任何席位）；不要为「没有席位」启动 reviewer 进程。
- 端口默认值沿用现有后端默认端口，放在 `config.py`；同一台机器并行跑多个 run 且要各用各的 reviewer 时，各自指定不同端口。

### 6.3 hub 的类型化 API（reviewer 包内部的契约，也是命令层 / AI 席 / 测试的共同入口）

```python
class Hub:
    def open_ask(self, req) -> Future[Settle]: ...          # 编号并挂起一问
    def submit(self, seq: int, answer: InjectAnswer | AuditAnswer, by: Literal["human","agent"]) -> SubmitAck: ...
    def propose(self, seq: int, proposal: Proposal) -> None: ...   # AI 席提交
    def discuss(self, seq: int, text: str) -> None: ...            # 人 → AI 讨论
    async def query(self, seq: int, q: ViewQuery) -> ViewAnswer: ...  # 读取前后都校验 seq
    def context(self, seq: int, section: str | None = None) -> ViewAnswer: ...
    def cancel(self, seq: int, reason: str = "该问已取消") -> SubmitAck: ...
    def history(self, n: int) -> list[HistoryEntry]: ...
```

契约：同一时刻只有一个 pending 问；`submit` 先答先得（已了结 / 编号不对 / 与问不配都回 `ok=False` 的 `SubmitAck`，不抛）；`query` 在 pending 已了结后回 `ok=False, text="该问已了结"`。
**命令层不含业务**：它把文本翻译成上面这些调用，解析失败只返回说明文本。
R6a 的 open_ask 对输入做独立快照，current/history 返回独立副本；历史摘要最多 50 条，
不保留整份带图请求。取消返回 cancelled 的 Settle，response 为空；正常 Settle 的 response
是原有 InjectResp / AuditResp。调用方或终端 EOF 退出都会解除 pending。
propose 与真正的 discuss 行为由 R7 接入，R6a 的 ask-ai 明确返回「没有 AI 席」。

### 6.4 命令层（人的入口用的语法）

所有行都是命令，标准命令行风格（`shlex` 切分；`say` / `overturn` / `ask-ai` 的正文取其后的原始整行文本，不做 shell 引号处理）：

```
ctx [--section 名]                       打印本问的 ReviewContext：默认节目录与行数，`--section` 打印某一节全文
trace [--run ID] [--episode ID] [--task ID] [--source 名] [--kind 账名] [-n 20] [--offset 0] [--content-limit 300]
recall [文本] [--episode ID] [--map ID] [--place 名] [--run ID] [-n 8]
frame <episode> <step> [--before|--after]   或   frame --latest   历史某步前 / 后帧，或 trace 里最近一条画面
brain-frames [--offset 0] [-n 2]         本问大脑看到的图（取自 ctx 里记忆对象的首末帧）
#（原行说明：）
history [-n 10]                          往期问答（本次 run 内）
say <文本>                               插话：让 LLM 带着这句话重做（仅插话问）
ok                                       插话问 = 没意见；审问 = 认账
overturn <理由>                          推翻（仅审问，理由必填）
ask-ai <文本>                            与 AI 讨论，AI 出新一轮 proposal（仅 AI 席存在时）
help [命令]                              用法
```

- 查询类命令（`trace` / `recall` / `frame` / `brain-frames`）的参数由对应 `ViewQuery` 变体的字段自动生成：字段名转 `--kebab-case`，`Literal` 字段成为选项，上下限与键校验由 Pydantic 给出，越界或非法键就地回一行原因，不抛。
- `help` 与参数表同样自动派生，加一个 `ViewQuery` 变体即同时出现。
- `RecallQuery.conditions` 的 Literal 键在 schema 中提供 hint 清单，自动派生 `--run-goal` / `--runs` 等选项；保留 `--run`、`--episode`、`--map`、`-n` 与 frame 位置参数的既定语法。
- `say` 用于审问、`overturn` 用于插话问：回「该命令不适用于本问」，不当作答复。
- **每条命令都有「等价于某个类型化调用」的测试**，防止命令层长出自己的行为。

### 6.5 线上协议（harness ⇄ reviewer，单跳）

沿用 `From[发起方]To[接收方][名][Req/Resp|Msg]` 命名，放发起方包：`schemas/harness/communication/`（harness 发起）与 `schemas/reviewer/communication/`（reviewer 发起）。

| 信封 | 方向 | 字段 |
|---|---|---|
| `FromHarnessToReviewerAskMsg` | harness → reviewer | `msg="ask"` `qid` `op: "inject"\|"audit"` `req`（`InjectReq` 或 `AuditReq`，含 `context`；记忆对象里的帧随之序列化） |
| `FromReviewerToHarnessAnswerMsg` | reviewer → harness | `msg="answer"` `qid` `resp`（`InjectResp` 或 `AuditResp`，含 `by`） |
| `FromHarnessToReviewerCancelMsg` | harness → reviewer | `msg="cancel"` `qid`（harness 线程退出或放弃该问） |
| `FromReviewerToHarnessHelloMsg` | reviewer → harness | `msg="hello"` `mode: "human"\|"ai"\|"both"`（连上即发） |

- 同一时刻只接受一个 harness 连入，且只有一个 pending 问；第二个连入被拒，说明里写明已有 run 占用。
- 同 qid 的请求素材签名必须相同。瞬时断线保留当前问，用户可离线答复；重连后原 qid 取回同一答案，不重开终端问。取消通知幂等且只影响该 qid。答复/取消缓存保留到 reviewer 进程退出，不随 50 条终端历史淘汰；只保存签名和答复，不缓存整份请求。
- cancel 与 ask 在客户端串行发送。关闭在连接可用时先发 cancel 再断开；连接已不可用时，退出通知只能尽力发送，服务端可能保留原问等待人工处理。AI 断线超时产生的取消留待后续重连投递。
- 人与 AI 之间、终端与 hub 之间**没有线上协议**：同进程，走 6.3 的类型化 API。
- 一问最多约 20 张图（brain-scope 的 `SCOPE_IMAGE_CAP`），回环传输可接受；若实测过大，改为只传帧引用、由 reviewer 经记忆 `recall` 取帧，另案。

### 6.6 显示

- 终端打印文本；`frame` / `brain-frames` 的结果图存成 PNG 到本机临时目录（`<temp>/pokemon-review/<seq>-<n>.png`），**打印路径、尺寸、前 / 后**，不在终端里画图。
- 结果文本里的画面一律显示为 `[frame omitted]`，要看画面用 `frame` / `brain-frames` 命令。
- 查询类结果以块打印（头行回显查询与条数，尾行 `--- 结束 ---`），不分页；条数与内容长度由 `ViewQuery` 的上限约束。
- 查询不算答复，打印完回到同一个提示符；提示行带 `help` 与 `ctx` 的提示。

---

## 七、AI 席（`reviewer/seats/ai/`，reviewer 进程内的 asyncio 任务）

### 7.1 结构与选型

- AI 席是 reviewer 进程内的一个模块，以 **asyncio 任务**运行在 hub 的事件循环里（不再有独立进程、跳 C WebSocket、`seed` / `turn` 信封，也不需要线程）。包内**禁止引用 brain 与 harness 实现**（只引 schema 与第三方库）；`pydantic-ai-slim[openai]` 只进 reviewer 进程，run 进程不装。
- **循环引擎选用 Pydantic AI（`pydantic-ai-slim[openai]`，R7 加入 `pyproject.toml` 并固定版本）。** 它只替我们承担「messages 数组、工具调用与回灌、参数校验与重试、结构化提交、用量上限」这一层通用循环；工具集、提交类型、预算、取消、取证规则、与 hub 的交互仍是我们自己的代码。
  - 选型依据：沙箱里用本地脚本化的 OpenAI 兼容服务（v2.57.0）实测通过——工具循环；输出类型自动成为 `final_result` 提交工具；参数非法回灌纠正并在重试用尽后抛 `UnexpectedModelBehavior`；`UsageLimits(tool_calls_limit=N)` 超限抛 `UsageLimitExceeded`；工具返回图片时自动追加带图 user 消息；首条 user 消息带图；总时限（`asyncio.wait_for`）与由工具内抛出的取消均能终止线程。这些**只证明库的控制力，不证明真模型行为**（见 7.3a）。
  - 同时**否决 OpenAI Agents SDK**：其结构化输出走 `response_format: json_schema` 而非提交工具，退出条件不如显式提交工具明确，且未验证所选模型对 `json_schema` 的支持。
  - 兜底：若 7.3a 探针或后续真机发现该库在所选模型上控制不住，退回**自写循环**（约百行，接口不变：`AiSeat.run_turn(...) -> Proposal`），hub 与命令层不受影响。
- 模型接入：`OpenAIChatModel` + `OpenAIProvider(base_url, api_key)`，取值来自 reviewer 入口配置 / `.env`（`AGENT_REVIEWER_MODEL`、`AGENT_REVIEWER_BASE_URL`、`DEEPSEEK_API_KEY`；缺省模型 `deepseek-flash`，缺省地址 `https://api.deepseek.com`）。AI 席与 `brain/providers.py` 各自独立（不回流）。思考模式通过 Pydantic AI `ModelSettings.extra_body` 发送 DeepSeek 官方的 `{"thinking":{"type":"disabled"}}`。
- 查询由工具函数直接调 reviewer 进程内的 `ViewReaders`（同一个实例，同一套 `ViewQuery`），不经过命令文本；每次查询由 hub 记一条 activity 并打印到终端。取消靠 `task.cancel()`。

### 7.2 有界工具循环（Pydantic AI 之上的我们自己的部分）

**协议选择：原生 `tools`（OpenAI 兼容 `chat/completions` 的 `tools` / `tool_calls` / `role: tool`），由库收发。** 工具参数 schema 由查询模型生成（接口边界靠类型说话，schema 复用）。

- **每问新建一个 agent，输出类型按 `kind` 区分**：审问 `output_type=AuditAnswer(verdict, note)`，插话问 `output_type=InjectAnswer(text)`；库把它注册为 `final_result` 提交工具，**因此每问只暴露与 `kind` 匹配的提交工具**，不另写 `submit_*`。`AuditAnswer` 在 `overturn` 时 `note` 非空，由模型校验器保证，违反即走库的重试回灌。
- **四个只读工具**：`read_trace`、`recall`、`read_frame`、`read_brain_frames`，参数是对应的 `ViewQuery` 变体；函数体只做一件事：经 hub 的 `query`（校验 `seq` 仍是当前问）调 `ViewReaders`（`read_brain_frames` 由 hub 用当前问快照回答），把 `ViewAnswer.text` 作为工具结果返回；`read_frame` 返回 `BinaryContent`（库自动追加带图 user 消息）。工具函数每次进入先检查取消事件，已置位即抛内部 `Cancelled`。
- **首条消息**：`system` 规则（§7.4）+ `user`（快照文本，**不带图**，更正 #20；图由 AI 按需调 `read_brain_frames` / `read_frame`）。
- **预算与降级（全部在 `run_turn` 内，代码约束，不靠 prompt）**：
  1. `UsageLimits(tool_calls_limit=AGENT_MAX_TOOL_CALLS)`；
  2. 超限抛 `UsageLimitExceeded` → 用 `capture_run_messages()` 取已有对话，交给一个**只有提交工具**的同类型 agent 再跑一次（追加「请现在提交结论」），仍失败则空提案；
  3. `retries=2`；重试用尽抛 `UnexpectedModelBehavior` → 空提案，日志一行；
  4. 总时限 `AGENT_TURN_BUDGET_S`：`asyncio.wait_for` 包住整次运行，超时 → 空提案；
  5. 取消：hub 了结该问时 `cancel()` 该 AI 任务（`CancelledError` 直接生效；若库把它包成别的异常，捕获后以**该问是否已了结**判定「被取消」，而非看异常类型），不产出 proposal；
  6. 任何未预期异常 → 捕获、日志、空提案，**不得影响 hub 与人席**。
- 一轮并行多个工具调用：由库逐个执行并全部回灌，仍计入工具调用次数。
- 允许工具名单固定为四个查询工具和 `final_result`；Pydantic AI 把这份名单转换为强制从名单中选一个工具。不能静态设置 `tool_choice="required"`：v2.57.0 会因此排除输出工具，并拒绝阻止 Agent 完成的配置。超限收尾只允许 `final_result`。
- 结构化输出：删除关键词子串判定（`_OVERTURN_WORDS` / `_ACCEPT_WORDS` / `_parse`）。

### 7.3a 官方协议核查与真实模型验收

R7 实现前查阅了 [DeepSeek Vision](https://api-docs.deepseek.com/guides/vision/)、[DeepSeek Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/) 与 [Pydantic AI v2.57.0 settings](https://github.com/pydantic/pydantic-ai/blob/v2.57.0/pydantic_ai_slim/pydantic_ai/settings.py)：DeepSeek 确认 `deepseek-flash` 支持 Chat Completions 图片输入与工具调用，并示范以 `extra_body` 关闭 thinking；Pydantic AI 支持图像与附加请求体，也说明静态 `required` 会排除输出工具。因此实现使用五个显式工具名白名单。文档**不等于账号上的真实模型联调**；保留一次性 `.pytest_tmp/r7_tool_choice_probe.py` 脚本，用户本机使用 `.env` 执行后补记结果。探针逐项看：
1. 是否返回合法 `tool_calls`；`prompt_tokens` 是否计入图（沿用 `ImageNotDelivered` 的静默丢图检测）；
2. 模型是否接受 `tool_choice="required"`；
3. 工具返回图片后追加的 user 消息（含 `image_url`）是否被接受并被模型利用；
4. 思考模式关闭的参数写法；
5. 参数非法后的纠正回灌是否能让该模型改正。
官方契约支持 → 可先按本节实现并由本地假模型测试库行为；真实探针是三种席位投产验收的一部分，不得标为已通过。若真实请求发现图像或工具调用不兼容，按探针结果缩减后重新验收；仍无法满足结构化提交时才退回自写循环（7.1 兜底）。

### 7.4 Prompt（规则 / 素材分离）

规则放 `reviewer/seats/ai/prompts/system.md`（复核者身份、两种权力、提交工具用法、查询工具说明、「只表态不改写」「推翻必给理由」）。素材（快照文本、表单、`round`、`max_rounds`）只由 seed 一次性渲染，讨论轮只追加增量。同一信息不两处传。
**取证规则**（何时该查）属于 prompt 与 AI 席自己的闸门，不由 harness 保证：审问在判定员说「已达成」时，先查最近几步的 trace 或结果画面核对再表态；插话问发现拆出的任务与此前失败重复或与已完成冲突时先查历史；没有可疑点直接交空意见。审问**至少一次查询**才接受提交的约束，列为 R7 的可选项，待真机观察后再定。

### 7.5 人席与 AI 席的权力对照（同权）

| 能力 | 人（CLI） | AI |
|---|---|---|
| 看快照 `ReviewContext` | ✅ `ctx` | ✅ seed 里 |
| 查 trace / 记忆 / 画面（同一个 `ViewQuery`） | ✅ 命令 | ✅ 工具调用 |
| 插话（让 LLM 带着这句话重做） | ✅ `say` | ✅ 插话类提交（`InjectAnswer`） |
| 审（认 / 推翻 + 理由） | ✅ `ok` / `overturn` | ✅ 审类提交（`AuditAnswer`） |
| 改写 | ❌ | ❌ |
| **每问查询次数** | 不限 | ≤ `AGENT_MAX_TOOL_CALLS` |
| **连续插话生效次数** | 不限 | ≤ `REVIEW_AI_INJECT_MAX_ROUNDS`（人一句清零） |

**权力一样，闸门不一样。** 最后两行是对「无人值守模型」的成本与收敛保护，不是权力差别；均为 `config.py` 里的实验旋钮。
AI 席是复核者而非第二个 judge：审的是「judge 结论与它自己摆出的证据是否一致」，prompt 明确禁止「重新判一遍目标成没成」。

---

## 八、插话重问循环与 AI 轮次阀（harness 侧）

两处循环（`plan_run::_elicit`、`plan_episode::_elicit`）共享 `elicit_with_review`，
从 `harness/reviewing.py` 导出；实现放 `harness/review_loop.py`，用临时 StateGraph 调度。
它不进入 run / episode / task 的持久状态，关闭 checkpoint 并显式使用 `durability="exit"`，
避免继承外层图的同步存档设置；不改变三层恢复拓扑或状态哈希。

```python
def elicit_with_review(ask_brain, ask_reviewer, *, max_agent_rounds) -> tuple[Outcome, str]:
    """问脑 → 亮给 reviewer → 有意见就带着重问。
    人（by=human）的意见永远生效，不设上限；连续的 by=agent 意见最多生效 max_agent_rounds 次。
    到顶后下一条 agent 意见不再生效：接受当前版，review_inject 账记 capped=True。"""
```

- 计数器：**连续**的 agent 生效轮数；一条 `by=human` 的意见把它清零；空回话（无意见）直接收尾。
- `max_agent_rounds = config.REVIEW_AI_INJECT_MAX_ROUNDS`（默认 3，**实验旋钮**，进 `config.py`）。
- `round` = 本插话点已亮出的次数 + 1（含人与 agent），传给 `InjectReq`；AI prompt 里写「本问第 {round} 轮；agent 连续生效上限 {max}」。
- `InjectReq` 同时携带 `max_agent_rounds`；两处循环总是传入实际配置值。独立请求可省略该上限，默认 `None`；`round` 默认 1。
- 每次实际询问由 `ask_inject` 返回同一份已落账的 `ReviewMark`，计数器由本次临时图持有；到顶后的空回话仍是无意见，`capped=False`。
- 人的插话不受 AI 轮次阀或图的默认递归步数限制；episode 原有拆解次数、时间预算及异常结算仍有效。
- harness 知道的只是「谁答的」标签，**不知道对面是什么实现**；`NullReviewer.by = "none"`。
- `ReviewMark` 增 `capped: bool = False`、`round: int = 0`（R4 加；`by` 已在 R2 加）；`capped` 与 `by` 同账可查，评测能区分「AI 到顶被截」与「AI 自己没意见」。
- 需同步：`schemas/harness/domain/trace_event.py::TraceEvent` 与 `trace/datastore/event.py::_Event` 是否需要新增顶层字段——`by` 经渲染写入 `content`、不需要；`capped` / `round` 同理，R4 开工时按同一依据复核。

---

## 九、编排模块（hub）

### 9.1 席位与模式（启动 reviewer 进程时显式指定，不靠「有没有人连着」推断）

| `ReviewSeats` | 行为 |
|---|---|
| `human` only | 终端接收一问；**无限等人**（与现状一致）；没有 AI，`ask-ai` 回「没有 AI 席」 |
| `ai` only | **无终端**（headless：不读 stdin、不倒计时、不打印 activity）；AI proposal 一到**立即提交**（`by="agent"`）；AI 席失败 → 空 proposal → `by="none"`（插话没意见、审认账），日志醒目 |
| `human` + `ai` | AI 出 proposal 后打印到终端并**启动倒计时**（`REVIEW_AI_COUNTDOWN_S`，默认 30s，**实验旋钮**，由 `AI_COUNTDOWN` 迁入 `config.py`）；人在倒计时内 `say` / `ok` / `overturn` 即接管（`by="human"`）；`ask-ai` 让 AI 出新一轮 proposal，倒计时重新开始；归零自动提交当前 proposal（`by="agent"`） |

### 9.2 一问的生命周期

1. `open_ask`：收到 harness 的 `ask`，编号 `seq`、挂起、终端打印该问（`human` / `both`）、起 AI 任务（若有 AI 席）。
2. AI 席工具循环（≤ `AGENT_MAX_TOOL_CALLS` 次、≤ `AGENT_TURN_BUDGET_S`）：每次查询经 hub 的 `query` 调读端口，hub 记 activity 并打印；提交（`final_result`）形成 `Proposal`，经 `propose` 交 hub。
3. 人的命令随时可到：查询结果只回给终端；答复先答先得。
4. 了结：`submit`（人）、倒计时归零或 `ai only` 的立即提交（agent）、harness 发来 `cancel`。hub 记进历史（至多 `HISTORY_LIMIT` 条，可跨 run 保留）、取消 AI 任务、向 harness 回 `answer`。
5. harness 侧 `inject` / `audit` 返回带 `by` 的回话；`by="none"` ⇔ `answered=False`。

### 9.3 并发

- reviewer 进程只有一个 asyncio 事件循环：hub、链路服务、终端读行、AI 任务都在其上，状态单线程修改，无锁。读端口里的同步调用（trace / `recall`）经 `run_in_executor` 放到线程池，不阻塞终端与倒计时。
- R6a 使用 asyncio.to_thread 执行同步读操作；终端命令任务由 TaskGroup 管理，慢查询期间继续接收人的答复。读取后若 seq 已失效，结果不交给下一问；EOF / 关闭时取消未完成命令，终端图像只保存到注入目录并打印路径、尺寸与来源，不在文字中输出编码。
- run 进程里只有 `RemoteReviewer` 的一条后台 WS 线程与被它阻塞的图线程，二者经 `Future` 交接。

---

## 十、reviewer 进程入口与终端（`python -m pokemon_agent.reviewer`）

- 启动：`python -m pokemon_agent.reviewer --seats human|ai|both [--url ws://127.0.0.1:<port>]`；读 `config.py` / `.env`（AI 席的模型与密钥配置、trace 与记忆的连接配置都在这里，与 run 同一份）；监听 `REVIEW_LINK_URL`，等 run 连入，连上即发 `hello`。
- R6b 可执行入口目前使用 `--seats human`；`--trace-backend` / `--trace-root` 必须与 run 指向同一后端和存储，`--memory-server-url` 缺省取 MCP_MEMORY_SERVER_URL。支持 `--env-file` 与 `--image-root`。没有 Langfuse 配置或 memory 地址时，只把对应读口标为未接入，不静默换后端；端口占用明确失败。
- 实际 stdin 由可关闭的 daemon 读线程送入事件循环，避免 Ctrl-C 后因阻塞 readline 等待线程池退出。行源 EOF 关闭应用并取消 pending，不启动 run。
- 终端（`human` / `both`）：读行 → 命令层（6.4）→ 打印；提示符带当前问的种类与 seq；`both` 时显示倒计时剩余秒数（仅显示，决定权在 hub）；空闲时提示「等待 run 连入 / 等待下一问」。
- `ai` 模式 headless：无终端，只写日志。
- **不**自动拉起 run（AI 不替用户启动长跑进程，沿用既有铁律）；reviewer 进程本身由用户启动。
- 画面存 PNG 并打印路径（见 6.6）。
- 一个 reviewer 进程可先后服务多个 run（同一时刻一个）；往期问答可跨 run 保留，仍受 `HISTORY_LIMIT` 封顶。

---

## 十一、配置与常量

| 名 | 位置 | 默认 | 判据 |
|---|---|---|---|
| `REVIEW_AI_INJECT_MAX_ROUNDS` | `config.py` | 3 | 实验旋钮 |
| `AGENT_MAX_TOOL_CALLS` | `config.py` | 6 | 实验旋钮 |
| `AGENT_TURN_BUDGET_S` | `config.py` | 90 | 实验旋钮 |
| `REVIEW_AI_COUNTDOWN_S` | `config.py`（由 `review_backend.AI_COUNTDOWN` 迁入） | 30 | 实验旋钮 |
| `REVIEW_LINK_URL`（启用地址） | `config.py` 或同名 env | None | 部署事实；未配置则 run 保持无头 |
| `DEFAULT_REVIEW_LINK_URL`（入口监听默认值） | `config.py` | `ws://127.0.0.1:8765` | 沿用旧后端端口；启动独立入口不自动启用 run 复核 |
| `REVIEW_LINK_LOST_TIMEOUT_S` | `config.py` | 120 | 实验旋钮；仅当最近一次 `hello` 的 `mode` 为 `ai` 时，链路丢失超过它则按 `by="none"` 继续 |
| `REVIEW_LAYERS` | `config.py` | `("run", "episode")` | 实验旋钮；加 `"task"` 开启 task 层审点 |
| `HISTORY_LIMIT` | `reviewer/hub/hub.py` | 50 | 模块私有物理量 |
| `TRACE_QUERY_MAX_ROWS` / `TRACE_QUERY_MAX_CONTENT` / `RECALL_QUERY_MAX_ROWS` / `FRAME_QUERY_MAX_IMAGES` | 查询模型文件 | 50 / 2000 / 8 / 2 | 模块私有物理量 |

删除：`CONSOLE_REVIEW_TIMEOUT`、`WEB_REVIEW_TIMEOUT`（随 R6c）。

---

## 十二、契约（assert 与显式异常）

| 位置 | 类型 | 内容 |
|---|---|---|
| `ReviewContext` | invariant | `layer` 与 `goals` / `tasks` 互斥一致 |
| `frames_of` | post | 返回的帧无 `None`、无重复；`render_context` 文本不含 `data:image` |
| `ReviewSeats` | invariant | `human or ai` |
| `RemoteReviewer.inject` / `audit` | pre | 发 `ask` 前已调用 `flush`（trace 已落盘） |
| `ViewReaders.read_trace` | post | 返回文本不含 `data:image` |
| `ViewReaders.*` | invariant | 只调用 `TraceReader.read_events` / `MemoryReader.recall`（窄 Protocol，测试用只含这两个方法的假件覆盖） |
| `elicit_with_review` | post | 返回时「连续 agent 生效轮数 ≤ max_agent_rounds」 |
| 各 Resp 构造 | invariant | `answered == (by != "none")` |
| `Hub.open_ask` | pre | 无未了结的问（同一时刻只有一问） |
| `tool_calls` 参数解析 | **显式异常** | 模型输出是外部输入：走库的校验重试回灌，重试用尽的异常由 `run_turn` 捕获转空 proposal，**不用 assert** |
| 读端口查询 | **显式返回** | 超时 / 读端口未接入 / 非法入参 / 该问已了结回 `ok=False`，不抛 |
| 命令解析 | **显式返回** | 非法命令或参数回说明文本，不抛、不进业务路径 |

新增 trace 事件：无新 `kind`；`review_inject` / `review_audit` 两账靠 `ReviewMark` 的 `by` / `capped` / `round` 表达。

---

## 十三、失败与降级

| 情况 | 行为 |
|---|---|
| 读端口未接入 / 查询非法 / 本问已了结 | 回 `ok=False` + 说明文本；AI 把它当工具结果继续，可再查或直接作答 |
| AI 工具循环耗尽 / 解析耗尽 / 总时限到 / 模型报错 | 空 proposal = 没人答：`human`+`ai` 退化为人决定；`ai only` 回 `by="none"`；run 不受影响；日志一行 |
| reviewer 进程未启动 / 断线 / 崩溃 | 见 6.2「断线语义」：`human` / `both` 或从未连上：run 持续重连并等待（每 30s 一条日志），重连后补发当前问；最近 `hello` 为 `ai`：超 `REVIEW_LINK_LOST_TIMEOUT_S` 按 `by="none"` 继续 |
| harness 线程退出（run 结束 / 异常） | `RemoteReviewer.close()` 发 `cancel`；hub 取消 pending 与 AI 任务，终端提示该问作废 |
| AI 插话到顶 | 接受当前版，`capped=True` 入账，继续往下走 |
| 链路端口被占 | reviewer 进程启动期 fail-fast，错误信息指明端口与 `REVIEW_LINK_URL` |
| 第二个 run 连入占用中的 reviewer | 拒绝并说明，不影响正在进行的那一问 |

---

## 十四、测试清单（用法示范风格，不连网、不调真模型）

| 测试 | 展示什么 |
|---|---|
| `test_audit_only_fires_at_judge_when_done` | 两层 `_settle` 不再调 reviewer；judge 判成才审（R1a 已有） |
| `test_task_graph_never_touches_reviewer_by_default` | 默认配置（`REVIEW_LAYERS` 不含 `task`）下 task 图无 reviewer 调用 |
| `test_task_judge_audit_when_layer_enabled` | 含 `task` 时：judge 判成才审；认账盖 `GOAL_DONE`；推翻则本 task 继续且 `last_judge` 带理由；不判成不审 |
| `test_task_review_context_carries_task_judge_req` | task 层的 `ReviewContext`：`layer="task"`、`task_id`、`brain_input` 为 `JudgeReq`，`goals` / `tasks` 皆 None；`frames_of` 取到 `history` 的前后帧 |
| `test_review_context_layer_exclusive` | run 层带 `tasks` / episode 层带 `goals` 构造失败 |
| `test_render_context_sections_and_dedupe` | 节齐全、无 `data:image`（含 `details` / `task_memories` 里的首末帧）、表只出现一次，带帧处只写「图 N 张」 |
| `test_render_context_follows_brain_scope_fields` | L0 渲染出 `details` 全文与 `run_index` 一行一条；L1 渲染出 `task_memories` 与 `episode_index`；`plan` / `task_table` 跳过 |
| `test_frames_of_dedups_and_labels` | `frames_of` 保持对象顺序、字符串相等去重、缺帧跳过、标签正确 |
| `test_brain_frames_query_pages_through_hub` | `read_brain_frames` 按 `offset` / `limit` 分页；该问了结后回 `ok=False`；视图对象不被调用 |
| `test_four_review_points_carry_context` | 四个调用点的请求带正确的 `layer` / `brain_input` 类型 / `step`；重问第二轮 `human_note` 是上一轮插话 |
| `test_view_readers_are_read_only` | 只含 `read_events` / `recall` 的假件；三种查询后假件无写调用 |
| `test_trace_query_can_read_other_run` | 指定 `run_id` 读到那个 run 的账；缺省读本 run |
| `test_read_frame_via_recall` | `read_frame` 经 `recall` 取到前 / 后帧；取不到回 `ok=False` |
| `test_reviewer_process_builds_no_game_or_brain_port` | reviewer 的装配入口只造 trace / 记忆读端口；源码里没有 game / brain 端口的构造 |
| `test_view_readers_strip_frames` | 事件里的 data URI 不出现在文本 |
| `test_trace_query_limits_rejected` | 越界 `last_n` / `content_limit` 被 Pydantic 拒绝；`RecallQuery.conditions` 非法键被拒 |
| `test_hub_first_answer_wins` | 同一问两个入口先后答复：第一个生效，第二个 `ok=False` |
| `test_hub_countdown_auto_submits_proposal` | `human`+`ai`：proposal 到达后倒计时归零自动提交（用假时钟）；`ask-ai` 重置倒计时；人答复接管 |
| `test_hub_ai_only_submits_immediately` | `ai only`：headless、proposal 立即提交；AI 失败 → `by="none"` |
| `test_hub_query_after_settle_is_rejected` | 该问了结后的查询回 `ok=False` |
| `test_command_equals_typed_call[...]` | 每条命令 ⇔ 某个类型化调用；非法参数回说明、不抛 |
| `test_help_derived_from_view_query` | 给 `ViewQuery` 临时加一个变体，`help` 与解析自动出现 |
| `test_link_roundtrip_over_loopback` | 回环 WS：`RemoteReviewer` ⇄ `ReviewerApp`（假终端）：`ask` 送达，`say` 了结，`answer` 回到 `inject` 的返回值；`cancel` 使 pending 作废；同一 `qid` 重发幂等 |
| `test_remote_reviewer_flushes_trace_before_ask` | 每次 `inject` / `audit` 发 `ask` 前 `flush` 回调已被调用 |
| `test_remote_reviewer_ai_mode_link_lost_returns_none` | 最近 `hello` 为 `ai`：链路丢失超时后返回 `by="none"`；`human` / 从未连上：不超时，重连后补发当前问（假时钟） |
| `test_reviewer_rejects_second_harness_connection` | 占用中第二个连入被拒并给出说明 |
| `test_cli_frame_saved_as_png` | `frame` 命令的结果存成 PNG 并打印路径 |
| `test_agent_tool_budget_then_forced_submit` | 用 Pydantic AI 的 `FunctionModel` 假模型（不连网）：一直要查询，到 `AGENT_MAX_TOOL_CALLS` 后走「只有提交工具」的收尾调用并得到 proposal |
| `test_agent_bad_submit_args_retried_then_empty` | 提交参数连续非法：库的重试回灌两次后抛异常，`run_turn` 转空 proposal 并日志一行 |
| `test_agent_only_exposes_matching_submit_tool` | 插话问的工具里没有 `AuditAnswer` 的提交，反之亦然 |
| `test_agent_overturn_requires_note` | 推翻缺理由被校验器拒绝并重试 |
| `test_agent_deadline_returns_empty` | 假模型慢于 `AGENT_TURN_BUDGET_S`（假时钟）→ 空 proposal |
| `test_agent_cancel_stops_task_without_proposal` | hub 了结该问后取消 AI 任务：不产出 proposal，不论异常被包成什么类型 |
| `test_agent_tools_call_view_only_via_hub` | 工具函数经 hub 的 `query`；该问已了结时回 `ok=False` 文本，不抛 |
| `test_reviewer_package_import_boundaries` | `reviewer` 包除 `__main__` 外只 import `schemas` 与第三方库；`__main__` 不 import harness / brain / world；`seats/ai` 之外不 import `pydantic_ai`；`reviewer_link` 不 import `reviewer` |
| `test_inject_loop_caps_agent_rounds_not_human` | agent 连续 N+1 次意见：第 N+1 次不生效且 `capped`；人的意见任意轮都生效并清零计数 |
| `test_by_and_answered_invariant` | 各 reviewer 的 Resp 满足不变式（R2 已有） |
| 集成：`FakeLLM + MockWorld` 跑一局 | 带 `NullReviewer` 全程不变；带回环 `RemoteReviewer` + 脚本化 `ReviewerApp` 触发一次插话 + 一次审 |

---

## 十五、验收（机械可验）

1. `grep -n ask_audit` 无命中；两层 `_settle` 无 reviewer 调用（R1a 已验）。
2. 默认配置（`REVIEW_LAYERS` 不含 `task`）下，task 层不调用 reviewer，行为与改动前逐位相同；开启后只在 judge·L2 判成时多一次 audit，无 inject。
3. `AuditReq.outcome` 类型仅含 judge 裁决。
4. reviewer（经 `RemoteReviewer` 送达）在 `plan_run` / `plan_episode` / 两层 judge 处收到的请求都带 `context`，`brain_input` 的类型与字段与该次发给大脑的请求一致。
5. 命令层与 AI 工具都只经 `ViewQuery`；`grep -rn "class .*Query" pokemon_agent/reviewer` 不出现自造的查询模型。
6. 三种查询前后：trace 与记忆的内容不变（读端口无写方法）；reviewer 进程的装配入口里没有 game / brain 端口的构造。
7. AI 席一问内的查询次数 ≤ `AGENT_MAX_TOOL_CALLS`；非法 / 越界查询到不了视图。
8. agent 连续 `REVIEW_AI_INJECT_MAX_ROUNDS + 1` 次插话 → 账里最后一条 `review_inject` 的 `capped == true`，且 `plan_*` 没有第 N+2 次重问。
9. 人在 `human`+`ai` 模式中途接管（`by=human`）后，agent 计数清零。
10. 所有 Resp：`answered == (by != "none")`（R2 已验）。
11. 死代码清理（3.4）清单逐项完成：R1b 之后 `grep -rn overturned pokemon_agent tests` 为空；R6c 之后无 `review_backend` / `WebReviewer` / `ConsoleReviewer` / `LiveFeed` 符号；R7 之后无 `agent_reviewer`；`state_schema_hash()` 除 R1b 与获用户授权的 R3b 外前后逐位相同；R3b 新增 TaskState.last_judge 后为 `28e96b09966dc94e`，需重打并核验 20 份评测存档。
12. AI 席的 LLM 请求体是 `messages` 数组 + `tools`；提交工具（`final_result`）只在对应 `kind` 的问里暴露；`pydantic_ai` 只在 `reviewer/seats/ai` 内被 import；run 进程（harness、`reviewer_link`）不 import `pydantic_ai`。
13. `ruff check . && ruff format --check .` 净；真机跑（`human`+`ai`、`ai only`、`human` only 各一次）交用户本机，AI 不拉起长跑进程。
14. 提问前 trace 已 flush（`RemoteReviewer` 的 `flush` 回调在每次 `ask` 前被调用）；reviewer 进程掉线时 harness 按 6.2 / 十三的语义继续。

---

## 十六、实施顺序（plan 的骨架，每步对应一条 CHANGELOG 与一个检查点）

| 步 | 内容 | 依赖 |
|---|---|---|
| R1a | 审点收敛（**已完成**，7eb5dba，CHANGELOG 514） | 无 |
| R2 | `by` / `answered` 不变式（**已完成**，6a85edd，CHANGELOG 515） | R1a |
| R3 | `ReviewContext`（不含画面）+ `frames_of` + 渲染（按 brain-scope 后的请求形状）+ 四个调用点构造 + `InjectReq` / `AuditReq` 的 `context` 字段；不动任何旧后端与控制台 | R1a、**brain-scope 已合入** |
| R3b | task 层可选审点：`ReviewContext.layer` 增 `task`、`task_id`；task 层 `review_and_judge` 在判成处 audit（受 `REVIEW_LAYERS` 控制，默认关）；`frames_of` 支持 `history` 帧；`build.py` 给 task 层装配 reviewer | R3 |
| R4 | `elicit_with_review` 与 AI 轮次阀 + `ReviewMark.capped/round` + `config` 常量 | R2、R3 |
| R5 | 前置核查（`recall` 取帧、trace 跨进程可见性与 flush 接口、`recall` 副作用）→ `reviewer/view/`：窄 Protocol `TraceReader` / `MemoryReader`、查询模型（含 `BrainFramesQuery`；`RecallQuery` 加 `run_goal` 键与 `runs` 提示）、`ViewReaders` 与测试（只新增 reviewer 包内文件，不碰 harness） | R3 |
| R6a | `reviewer/` 的 hub（含对 `read_brain_frames` 的回答）+ 命令层 + 终端席（`human` only）+ `ReviewerApp`（进程内，无网络）+ 导入边界测试 | R4、R5 |
| R6b | 链路：线上信封 + reviewer 侧本地 WS 服务 + reviewer 进程入口（`python -m pokemon_agent.reviewer`）+ run 侧 `reviewer_link/RemoteReviewer`（flush、断线语义）+ `build.py` 装配（`REVIEW_LINK_URL` 有值则装 `RemoteReviewer`）+ 回环测试 | R6a |
| R6c | 删旧栈：`ConsoleReviewer` / `WebReviewer` / `review_backend` / 跳 A·B 信封 / `LiveFeedTrace` 与 `live_feed_url` / 旧常量与测试 / 文档状态说明 | R6b |
| R7 | 0）图 + tools + `tool_choice` 探针（用 Pydantic AI）；AI 席（`reviewer/seats/ai`，Pydantic AI 之上的有界循环）+ `human`+`ai` / `ai only` 模式 + 倒计时；旧 AI 栈已随 R6c 删除；`pyproject.toml` 加依赖 | R6c |
| R8 | （暂缓）网页入口：在同一 hub 上加网页壳 | R7 |
| R9 | 文档同步：`reviewer.py` 表格、`docs/agent_reviewer`、规范 §四第 3 条（须用户点头） | R1a–R7 |
| R10 | 用户本机真机跑（三种模式） | R7 |
| R1b | 删 `overturned` 字段 + 全部读方 + 结算账 `audit` 键；**重建 20 份评测存档**（须用户授权、真实模拟器；等评测任务合入后） | R1a、用户授权 |
| R11 | 死代码收尾自查（3.4 的 grep 清单） | 其余全部 |

---

## 十七、风险与取舍

| 项 | 说明 |
|---|---|
| 成本 | 每问最多 `1 + AGENT_MAX_TOOL_CALLS` 次视觉调用；每次带完整对话。brain-scope 之后快照文本与大脑自己那问等量（L0 含最多 `max_episodes=10` 条局记忆全文），故首条消息不带图（#20）、图按需取，每次 `read_brain_frames` 至多 `FRAME_QUERY_MAX_IMAGES` 张。上限由常量控制，必要时先把工具数降到 2–3 |
| task 层审点 | 默认关。开启后每个 task 判成时阻塞一次（每 episode 至多 `episode_max_tasks` 次）；`human` 模式需有人值守，`ai only` 无此顾虑。不做 task 层 inject（#22） |
| 延迟 | 首个 proposal 变慢；`human`+`ai` 的倒计时从 proposal 到达起算 + `activity` 流让人看到进度；`AGENT_TURN_BUDGET_S` 兜底 |
| 原生 function calling 的前置不确定 | 图 + tools 同请求、`tool_choice="required"` 是否可用均未证实（见 7.3a）；以探针结果决定，有降级路径 |
| 引入 Pydantic AI | 新增第三方依赖，其消息与重试逻辑不完全受我们掌控；沙箱探针只用脚本化假服务，未接真模型。缓解：版本固定、仅 `seats/ai` 可引、`run_turn` 接口不暴露库类型，必要时退回自写循环（7.1 兜底） |
| AI 是否会合理地查证 | 触发完全由模型自己判断，没有程序化条件；风险是不查或乱查。缓解：prompt 的取证规则 + 次数上限 + 审问「至少查一次」的可选闸门；真正表现只能真机跑才知道（R10） |
| trace 跨进程可见性 | reviewer 从另一个进程读 trace，批量落盘（如 Langfuse）可能读到旧数据；缓解：`RemoteReviewer` 每次 ask 前调 `flush`（R5 核查接口存在性与效果）；做不到则 `read_trace` 的头行标注「可能不含最近几秒」 |
| 人审点减少 | task / episode 结算不再过人（3.3）；若评测发现机械结算误判多，再单独开「结算复核」 |
| harness 知道 `by` | 知道的是**回话标签**，不是实现类型；这个标签本就是评测口径（`answered`）的细化 |
| 同权的两处非对称 | AI 有查询次数与连续插话两道闸，人没有；若要连这两道闸都对称，改成同一个常量即可 |
| 同一 run 只许一问 | 沿用现状 |
| reviewer 进程与 run 进程的启动顺序与断线 | 先起 reviewer、再起 run；断线语义见 6.2 / 十三；`ai only` 下若 run 先起而 reviewer 未起，run 会一直等（日志每 30s 提示）——已接受 |
| AI 席与 run 的隔离 | reviewer 进程独立，AI 席崩溃 / 超时只影响 reviewer；`pydantic-ai` 依赖不进 run 进程 |
| 仅终端 | 无画面内联与实时时间线，画面落临时文件；网页壳以后在同一 hub 上加（R8） |

### 17.1 被否决：把 reviewer 通信改成 A2A（Agent2Agent）

方案：后端做成共享类，harness 与 reviewer 各自作为 A2A agent 直接互通。

- 好处：一问一答天然是 Task，状态（working / input-required / canceled）现成；流式更新可承载 activity；Agent Card 可声明检索能力；合规 reviewer agent 可替换接入。
- 代价：harness 需在跑图时开服务端监听；依赖 SDK 或自实现子集（规范刚到 1.0，演进快）；人与 AI 的仲裁要新归处；已设计的线上协议大部分重写。
- **决定性缺陷**：A2A 把对方 agent 当不透明黑盒，调用方只能发消息、查状态、订阅、取消，**不能编排对方内部逻辑**（强制取证、规定工具顺序与步数、中途纠正推理）；检索是工具调用而非 agent 间自治协作，包装成任务既重又别扭。
- 结论：不采用。若将来确有第三方 agent 互通需求，再评估只在「请复核」一步借用其形态。

### 17.2 被否决：单独加 tool 层门面 / 用 MCP 做 harness 与 reviewer 的边界

- 不加 tool 层门面：`Reviewer` 端口已带类型化信封，记账在 `harness/reviewing.py`，等价于门面；再加一层只是改名。
- MCP 不做边界：MCP 是请求-响应的工具调用模型，不适合「长时间阻塞等人 + 同一问内 AI 反向查 harness + 多入口推送」。
- 保留的门：hub 的类型化 API 保持干净、不带命令层或任何协议的特例；将来要让任意外部 agent 充当 reviewer，可把 hub 包成一个 MCP 服务（只读查询工具 + `submit_*`），作为薄壳，不动 hub。

### 17.3 采纳：用 Pydantic AI 做 AI 席的循环引擎

- 采纳理由：通用循环（消息数组、工具回灌、校验重试、输出类型即提交工具、用量上限、工具图片回灌）已现成且在脚本化服务上实测通过；自写同等功能约百行，但重试与图片回灌的细节要自己踩坑。
- 不采纳其他：OpenAI Agents SDK（结构化输出靠 `json_schema`，退出条件不明确）；smolagents（让模型写代码执行，引入沙箱问题）；Instructor（无循环）。
- 代价与边界：见 §十七风险表「引入 Pydantic AI」；库类型不穿出 `run_turn`；总时限与取消不是库的开箱功能，由我们在 `run_turn` 里补齐（7.2）。

### 17.4 被取代：reviewer 并入 run 进程（v2 / v3 的拓扑）→ v4 reviewer 独立进程

- v2 / v3：reviewer 是 run 进程里的一个对象，AI 席进程内线程，人经本地 WS 连独立 CLI；harness 持有 `ReviewView` 并回答查询。
- v4（用户 2026-10-17）：人、AI、hub、读端口同在一个独立进程，进程边界移到 `Reviewer` 端口上。理由：①查询权属于 reviewer 而非 harness，harness 不再背 `ReviewView` / `ViewAware` / `bind_view`；②AI 席与 run 隔离，线程安全核查项消失；③`pydantic-ai` 依赖只进 reviewer 进程；④人与 AI 在同一事件循环里，AI 不需要线程；⑤全程只有一条跨进程线路。
- 代价：先起 reviewer 再起 run；多终端同连取消；本地 trace 在提问前 flush 后可见，Langfuse 仍可能延迟；`read_world` 取消。
- 仍成立的否决：不用 A2A、不用 MCP 作边界、不加 tool 层门面（17.1 / 17.2）；链路是自己的类型化信封。

---

## 十八、落码前须核对（本 spec 起草时未读全）

1. **（R5 前置）** `recall(conditions={"episode_id": …})` 返回的 act 族条目 payload 是否带 `before_frame` / `after_frame`；单次条数上限是否足以覆盖一局；经 MCP 远程版时是否仍如此。不满足则 `read_frame` 不上线。
2. **（R5 已裁决）** 实测 MCP recall 会在外部编辑后更新 index.json / vectors.jsonl；用户确认这是客观更新、允许保留。只读保证限定为无业务写操作、不改记录正文，继续复用现有 recall，详见 `r5-audit.md`。
3. **（R5 前置）** trace 后端（本地文件 / Langfuse）在 run 进程 flush 之后，另一进程能否立即读到；`TraceToolPort` 是否已有 `flush`（或等价）接口；没有则要在 trace 模块加一个（触及 trace 能力面，须用户拍板）。
4. `build.py` 里 `RemoteReviewer` 的装配位置、`flush` 回调的来源（trace 端口），以及 `reviewer` 参数从「传实例」到「装配期按 `REVIEW_LINK_URL` 构造」的入口改法（`check_harness` 等）；reviewer 进程 `__main__` 如何按 run 的 trace 配置造读端口（同一份 `.env` / `config`）。
5. trace 读端口与 `recall` 在 reviewer 进程里的线程 / 协程安全：hub 单事件循环，同步端口需放线程池（`run_in_executor`），核查它们能否被并发调用。
6. 探针（7.3a）结果；Pydantic AI 的固定版本号与 `ModelSettings` 里关闭思考模式的字段名；AI 席模型 / 密钥配置项沿用旧 `agent_reviewer` 的名称还是并入 `config.py`。
7. 新增状态字段是否会再次改变 `state_schema_hash()`：R2–R7 新增的类型（`ReviewContext`、`ReviewMark` 字段、信封、reviewer 包的模型）都不在三个状态模型里，应不改哈希；**每步完成后复核**，若变了立即停下汇报。
8. 实时流删除后，`TraceTool` 与 Langfuse 的装配顺序（`live_feed_url` 的组合语义）有无其他依赖；`docs/eval/langfuse-plan.md` 提到的组合语义需同步说明。
9. （R3 前置，brain-scope 合入后）三种请求的实际字段名（`details` / `run_index` / `episode_index` / `observation` / `knowledge`）、帧字段名与 `ReviewContext` 渲染的跳过规则，以合入后的代码为准重核；`brain_input` 的联合类型是否仍只含这三种。
10. （R5 前置）`recall` 新增的 `run_goal` 条件与 `runs` 提示经 MCP 远程版同样可用；`RecallItem.kind` 含 `run`；`RecallQuery` 的 `limit` 上限 8 小于大脑自己召回用的 `10**6`，所以「大脑看到的全部」靠 `brain_input` 里的对象，`recall` 只用来探索。
11. （R1b）与 brain-scope CP8 存档重打的次序，见 plan §八。
