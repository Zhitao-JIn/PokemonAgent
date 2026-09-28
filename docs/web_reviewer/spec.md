# Web Reviewer spec —— 人在环第三实现：独立后端 + 网页（WebSocket 推送）

> 状态：v1（0925）。前身 `spec-v0.md`（原 `docs/PLAN_web_reviewer.md`，写于 checkpoint-v2 之前）。
> 本文是设计，不含实现；实施顺序见 §10，plan 另写 `plan.md`。
>
> **用户已定**（v0 起沿用）：①做前端、删 FileReviewer；②三方（源程序 + **独立后端** + 前端），
> **后端推给前端，不轮询**；③AI 不再是驱动方；④信封成对；⑤**插话只在 plan 格、审只在
> `review_and_judge` 格**；⑥用 WebSocket（`websockets` 库，不手写帧）。
> **0925 新定**：超时 30s（Q7）；Q2/Q5/Q6/Q8 交 AI 判断（结论见 §9）；W2 后重录一次真机 run（§4.5）。

---

## 〇、相对 v0 的更正（核过代码）

| # | v0 的说法 | 实际 / 问题 | v1 处置 |
|---|---|---|---|
| 1 | 五处调用点直接调 `reviewer.inject/audit` | checkpoint-v2 后统一经 `harness/reviewing.py` 的 `ask_inject` / `ask_audit`，问完记 `review_inject` / `review_audit` 一笔；回放由 `tools/replay/tape_reviewer.py` 顶替人 | 改签名要连带 `reviewing.py`、`TapeReviewer`、`ReviewMark`（§3.3） |
| 2 | 后端 = `ThreadingHTTPServer` + 另一个线程里的 `websockets.serve()`，**一个固定端口**，`/ws` 是其中一个端点 | **两台服务器不能共用一个端口**，v0 自相矛盾 | 只起**一台** `websockets` 服务器，源程序与页面**都走 WebSocket**；`GET /`、`GET /health` 用 `process_request` 回普通 HTTP（§5） |
| 3 | 跳 A 回程信封叫 `FromReviewBackendToHarness…Resp` | 违反 AGENTS §十二第 1 条"两半都放发起方、Resp 沿用发起方方向名"——v0 §3.1c 自己引了这条又违反 | 改为 `FromHarnessToReviewBackend…Resp`（§3.2） |
| 4 | 推送叫 `…AskPush` | §十二只有 Req/Resp 两种后缀；无返回的单向消息按 `ResetReq` 先例 = 只有 Req | 改为 `FromReviewBackendToFrontendAskReq` 等（§3.2） |
| 5 | `JudgeReq.human_note` 保留，"plan 侧插话仍走它" | plan 侧走的是 `PlanOnceReq` / `DecomposeReq` 各自的 `human_note`；`JudgeReq.human_note` 唯一生产者就是要删的 episode 重问循环 | W2 后**删** `JudgeReq.human_note` 及 prompt 里拼它的那段（§4.3） |
| 6 | Q7「`REVIEW_TIMEOUT=300s` 沿用」 | 300s 是 `file_reviewer.DEFAULT_TIMEOUT`；控制台是 `CONSOLE_REVIEW_TIMEOUT=30s` | 用户定 30s（§5.3） |
| 7 | 超时 / 断连回默认值，与真答无从区分 | 评测 V7「判定是否可靠」要人的标注；"认账"和"没人答"混在一起，标注就是脏的 | 两个 Resp 加 `answered: bool`，进 `ReviewMark`（§3.1） |
| 8 | 后端放 `pokemon_agent/harness/review_backend/` | `python -m pokemon_agent.harness.review_backend` 会先执行 `harness/__init__.py`，把 run 图、langgraph 全拉起来；后端一行 harness 代码都不用 | 放顶层 `pokemon_agent/review_backend/`（Q2，§6.2） |
| 9 | 行号（`:74` `:94` `:98` `:113` `:133`） | 已漂移 | 本文只写文件 + 函数名，不写行号 |
| 10 | 记忆清单 `MEMORY-review.md` 等 | 仓库里没有这些文件（是旧会话的 AI 记忆） | 从删除清单拿掉 |
| 11 | 审裁决时人的 `note` 落 `record_verdict(human_note=…)` | 那是 trace；plan 与 trace 之间**刻意没有数据通路**（`PlanOnceReq` docstring）——人推翻了，plan 不知道为什么，会拆出同样的东西、judge 又判成，人只能一直推翻。模型判「没成」时的 `why` 同样到不了下一次 plan | 本层裁决反馈经 state 回到 plan（§4.6，用户 0925 批） |
| 12 | —— | `Reviewer.audit` docstring 说「note 拼进后续提示词最末尾」，实际是写进表里那一行 | 改 docstring |

---

## 一、一句话结论

把「人」从一对文件（`.workbuddy/review_request.json` ↔ `review_answer.txt`）换成**一个常驻后端 + 一个网页**：

```
            ① WS：AskReq                    ② WS：AskReq（推送）
源程序 ─────────────────────► 后端 ─────────────────────► 网页
(WebReviewer，        ◄──── ④ WS：Resp  ◄──── ③ WS：AnswerReq / AnswerResp
 run 进程内)                (一台 websockets 服务器，一个端口)
```

源程序侧多一个 **WebSocket 客户端**（`Reviewer` 第三实现，同步 API，阻塞等答），后端是**独立常驻进程**，
网页是后端 `GET /` 吐出的单页。落点规则一句话：**插话只在 plan 格，审只在 `review_and_judge` 格**。

## 二、为什么换掉 FileReviewer（v0 §1，核过仍成立）

1. **请求里没有内容**：`FileReviewer` 只落 `{form_kind, prompt, ts}`，页面没法显示在审什么。
2. **回话只有一个字符串**：`FileReviewer.audit()` 恒认账，审走不到。
3. **文件握手的复杂度**：mtime 判新鲜、零删除协议、原子 tmp+rename，全为绕过"没有共享内存"。

## 三、信封

### 3.1 进程内（harness ↔ `Reviewer` 实现）

| 信封 | 字段 | 状态 |
|---|---|---|
| `FromHarnessToReviewerInjectReq` | `prompt` `form` `form_kind` | 不动 |
| `FromHarnessToReviewerInjectResp` | `text` `answered` | **新增**；Protocol `inject(req) -> InjectResp` |
| `FromHarnessToReviewerAuditReq` | `run_id` `episode_id` `task_id?` `outcome` `events` | `outcome` 加成员 `FromHarnessToBrainToolJudgeResp`（§4.3） |
| `FromHarnessToReviewerAuditResp` | `verdict` `note` `answered` | **分文件**；加 `answered` |
| `AuditVerdict` | — | 挪 `schemas/harness/domain/audit_verdict.py`（三跳共用） |

`answered=False` 表示"没人答"（超时 / 后端断连 / `NullReviewer`），此时 `text=""` 或 `verdict=ACCEPT`——
**行为**与今天逐字相同，只是账上分得清。有了 `answered`，`inject` 返回的就是结构化载荷，按 §十二第 1 条本来就该有 Resp。

### 3.2 跨进程（线上 JSON，全部 pydantic 校验）

**跳 A：源程序 ↔ 后端**（发起方 harness，放 `schemas/harness/communication/`）

| 信封 | 字段 |
|---|---|
| `FromHarnessToReviewBackendInjectReq` | `run_id` `prompt` `form_kind` `form_text` `timeout_s` |
| `FromHarnessToReviewBackendInjectResp` | `seq` `text` `answered` |
| `FromHarnessToReviewBackendAuditReq` | `run_id` `episode_id` `task_id?` `prompt` `outcome_text` `events: list[str]` `timeout_s` |
| `FromHarnessToReviewBackendAuditResp` | `seq` `verdict` `note` `answered` |

**跳 B：后端 ↔ 网页**（放 `schemas/review_backend/communication/`，理由见下）

| 信封 | 方向 | 字段 |
|---|---|---|
| `FromReviewBackendToFrontendAskReq` | 后端 → 网页 | `seq` `run_id` `kind`（inject/audit）+ 跳 A 的展示字段 + `deadline`；无 Resp |
| `FromReviewBackendToFrontendSettleReq` | 后端 → 网页 | `seq` `by`（human/timeout/harness_gone）+ 答案摘要；无 Resp。网页据此清屏、入历史 |
| `FromFrontendToReviewBackendAnswerReq` | 网页 → 后端 | `seq` `text?` / `verdict?` `note?` |
| `FromFrontendToReviewBackendAnswerResp` | 后端 → 网页 | `seq` `ok` `reason`（已答 / 已作废 / seq 不对 → `ok=false`） |

- `seq` 由**后端**分配（全局单调、跨 run），通过 Resp 回给源程序进日志；源程序不造 seq。
- `timeout_s` 由源程序给（读 `config.WEB_REVIEW_TIMEOUT`），后端**不 import config**、只按请求计时——超时的主人是后端（它要广播作废），源程序 `recv` 多等 5s 兜底。
- `form` 本体不出进程：线上只有源程序渲染好的文本（§6.3）。
- 跳 B 为什么不放 `schemas/frontend/`：AGENTS §十二的强制范围是 Harness ↔ 门面；网页是 JS，这四件唯一的 Python 消费者是后端，跟后端住一起。AGENTS 里"`schemas/frontend/` 已删除"那段要补一句（**改 AGENTS 需用户批**，放进 W7）。

### 3.3 连带改动（v0 漏的）

| 件 | 改什么 |
|---|---|
| `harness/reviewing.py` | `ask_inject` 取 `resp.text` 返回（调用方不动），`ReviewMark` 记 `answered` |
| `schemas/harness/domain/review_mark.py` | 加 `answered: bool`（必填，无缺省——旧记录已清，不做兼容）；加 `wait_s: float`（问到答的秒数，§5.3 的 30s 够不够靠它定）；**审也填 `form_kind`**（`EpisodeOutput` / `TaskOutput` / `JudgeVerdict`），四个审点在账上才分得开——评测算 judge 假阳率要挑出「审裁决」那几笔 |
| `judge_verdict` 账（`record_verdict`） | 加 `audit`（accept / overturn / 空=没问人），与 `settle_goal` / `settle_task` 的 `audit` 同款；推翻后记的 `termination` 是翻转**后**的 |
| `tools/replay/tape_reviewer.py` | 从磁带重建 `InjectResp` / `AuditResp`（含 `answered`） |
| `NullReviewer` / `ConsoleReviewer` | 签名跟随；Null 回 `answered=False`，Console 超时回 `answered=False` |

## 四、落点规则：插话只在 plan 格，审只在 `review_and_judge` 格

### 4.1 现状

| 层 | plan 格 | `review_and_judge` 格 |
|---|---|---|
| run | `plan_run` 插话 `PlannerOutcome`（合规） | `_settle` 审一局（合规）；judge 裁决**零人窗口** |
| episode | `plan_episode` 插话 `Decomposition`（合规） | 审 task 定案（合规）；**judge 裁决走插话 + 带话重问**（不合规） |
| task | 无 | 无 |

### 4.2 改成

| 层 | plan 格：插话 | `review_and_judge` 格：审 |
|---|---|---|
| run | `PlannerOutcome`（不动） | ①审一局（不动）②**补**：审 judge 对 `run_goal` 的裁决 |
| episode | `Decomposition`（不动） | ①审 task（不动）②**改**：judge 裁决的插话 → 审 |
| task | 无（刻意，§4.4） | 无 |

插话 2 处、审 4 处，两层同构。

### 4.3 审裁决的机制

- `AuditReq.outcome` 加成员 `FromHarnessToBrainToolJudgeResp`，页面按成员渲染"机械结算 / 模型裁决"两副面孔。
- 只在 `verdict.done` 为真时问（裁决"没成"时推翻 = 人宣布达成，那是插话/新目标的事，不在本次范围）。
- OVERTURN 的后果全由 harness 盖章：run 层 → `GOAL_DONE` 作废，`termination` 回机械三类，run 继续；episode 层 → `GOAL_DONE` 作废，本局继续下一个 task。人的 `note` 进本层 `last_judge`（§4.6）让下一次 plan 看见，同时落 `record_verdict(human_note=…)` 留账。
- **删**：episode 层"带话重问"循环、`FromHarnessToBrainToolJudgeReq.human_note` 字段、judge prompt 里拼接它的那段。
- **行为变化**：以前人说一句让模型改口，现在人直接翻转，模型不再有第二次机会——与"判定只认达成"同向。

### 4.4 task 层零人在环 = 刻意

task 层一圈 = 一个键，逐键问人会把人变成打分机。定案，不留悬案。（0925 复核，仍不加）

- **审已经覆盖到 task**：episode 层「审 task」审的就是 `TaskOutput`，它的成败来自 task 层 judge——task judge 的裁决在上一层被人审过了，不必在 task 层再审一遍。
- **插话没有落点**：task 层没有 plan 格，它的"计划"就是 episode 拆出来的那一行，人要改它在 episode 的 plan 格插话。
- **看得见就够了**：有了 §6.4 的实时画面，人能看着 task 跑；真正缺的是"现在就停下这个 task"——那是**控制**不是审，留作后续（跳 B 的双向通道已留好）。

### 4.5 对回放的影响

W2 之后，已录的 run（如 `checkpoint_check/ckptcheck-0925-131754`）在 episode judge 那一格录的是 `review_inject`，新代码取 `review_audit` → `ReplayDiverged`。**用户定：W2 后在本机重录**（`check_checkpoint.py --record`），旧 run 留作备份。磁带不做旧事件兼容。§4.6 改了 decompose / plan 的 prompt，旧 run 的 `model_call` 也对不上，同样靠重录解决。

### 4.6 本层裁决的反馈回到 plan（0925 补）

**现状**：审结果的反馈 plan 看得见（推翻的 note + `overturned` 写进表行，`run_plan.py` / `decompose.py` 渲染成 `FAILED（人审推翻）… · note`；子层 judge 的依据经总结进记忆）。**本层 judge 的反馈看不见**：episode judge 判「没成」的 `why` 只落 `state.judge_reason`、下一圈就被覆盖，`DecomposeReq` 没字段装它；run judge 的 `why` 谁都不读；审裁决的人话按 v0 只进 trace。

**改成**：

- 新 domain 模型 `schemas/harness/domain/judge_feedback.py`：`JudgeFeedback{done, why, audit: AuditVerdict | None, note}`——模型说了什么、人认没认、人的理由。
- `EpisodeRunState` / `RunState` 加 `last_judge: JudgeFeedback | None = None`。`review_and_judge` 问过模型、且本层**继续跑**时写入（模型判没成；或判成被人推翻）；判成且认账则本层收工，不写。每圈覆盖，只留最近一次。
- `FromHarnessToBrainToolDecomposeReq` / `FromHarnessToBrainToolPlanOnceReq` 加 `last_judge: JudgeFeedback | None`，`plan_episode` / `plan_run` 从 state 取了放进去。
- prompt（`decompose.py` / `run_plan.py` 及模板）加一段「上一次本层判定」：模型判了什么、依据；人推翻时加「人推翻：<note>」。为空不出这一段。与 `human_note` 分开——`human_note` 是对**这一版计划**的插话，`last_judge` 是对**目标达成度**的反馈。
- 走 state 不走 trace，守住「plan 只读 state 与记忆」。
- **行为变化**：拆解 / 规划的 prompt 多一段，模型会朝「还差什么」拆——这是本条要的效果，真机 run 时留意有没有被带偏。

## 五、通信

### 5.1 后端端点（一台 `websockets` 服务器，缺省 `127.0.0.1:8765`）

端口是部署配置，不进 `config.py`（那里只放实验旋钮，见其模块说明）：后端 `--port`，
`WebReviewer` 的地址由 `check_harness.py` 传入。

| 路径 | 类型 | 谁连 | 语义 |
|---|---|---|---|
| `GET /` | HTTP（`process_request` 回） | 浏览器 | 单页 |
| `GET /health` | HTTP（同上） | 人 / 脚本 | `{ok, pending_seq, harness_connected}` |
| `/harness` | WebSocket | `WebReviewer` | 一次 run 一条长连接：连上即探活；发 Inject/AuditReq，收对应 Resp |
| `/ui` | WebSocket | 网页 | 连上先补发当前 pending 的 AskReq + 最近 50 条 Settle；此后收推送、发 AnswerReq、收 AnswerResp |

- **同一时刻只许一条 `/harness` 连接**：第二个 run 连进来 → 以 1008 关闭并附原因（"已有 run 在用后端"），源程序构造时即炸。
- 图是串行的，一条 `/harness` 连接上同时最多一个未答 ask；收到第二个 → 协议错，关连接（跨进程输入，不用 assert）。
- 调试兜底：`python -m websockets ws://127.0.0.1:<port>/ui` 可手敲 AnswerReq，不再单开 HTTP POST 端点。

| `/feed` | WebSocket | run 进程的 `LiveFeedTrace`（§6.4） | 单向：源程序把每条刚落盘的 trace 事件推上来，后端转播给 `/ui`；无回话 |

### 5.2 为什么源程序也走 WebSocket（替代 v0 的长挂 HTTP POST）

- 一台服务器、一个端口，不用在 HTTP 线程与 asyncio 循环之间搬状态；
- `websockets.sync.client` 是同步阻塞 API，`recv(timeout=…)` 直接就是"等人答"，比长挂 POST 更贴；
- 连接本身就是"这个 run 还活着"的信号：run 进程死了，后端立刻知道并广播作废（`by=harness_gone`）；
- 代价：`curl` 不能直接答了（用上面的调试兜底）。

### 5.3 超时与降级

| 情形 | 行为 |
|---|---|
| 人答了 | 回人的答案，`answered=True` |
| 人没答 | 后端到 `timeout_s`（`config.WEB_REVIEW_TIMEOUT = 30.0`）回默认值（插话 `""` / 审 `ACCEPT`），`answered=False`，广播 Settle(`timeout`) |
| 构造时连不上后端 | 抛 `OSError` 当场停，提示先起后端 |
| run 中途后端断了 | **降级**：本问与之后每一问都按默认值、`answered=False`，每问一行醒目 `[review]` 日志；不重连（Q6） |

## 六、源程序侧与后端

### 6.1 `WebReviewer`（`pokemon_agent/harness/web_reviewer.py`）

构造：`WebReviewer(run_id, url=…, timeout=WEB_REVIEW_TIMEOUT)`，连 `/harness`，失败抛 `OSError`。
`inject` / `audit`：渲染 → 组跳 A 信封 → `send` → `recv(timeout + 5)` → 转成进程内 Resp。每问每答一行 `[review]` 日志。
不起服务、不存状态、不重连。依赖只有 `websockets`。

### 6.2 后端（`pokemon_agent/review_backend/`，顶层包）

```
pokemon_agent/review_backend/
    __init__.py    ReviewBackend：状态（seq / pending / history）+ 两个 WS handler + process_request
    page.py        PAGE_HTML（单页内联 HTML/CSS/JS）
    __main__.py    python -m pokemon_agent.review_backend [--port]
```

- 只 import `schemas`（跳 A、跳 B 信封与 `AuditVerdict`），不碰 harness / tools / brain / world / memory。
- 单个 asyncio 事件循环，状态不需要锁。pending 用 `asyncio.Future`，`wait_for(timeout_s)`。
- 历史 = 内存 `deque(maxlen=50)`，不落盘（定案账在 trace）。
- 端口固定，被占即报错退出（"上次的后端还在跑？"），不自动挪。
- **你本机起**：①`python -m pokemon_agent.review_backend` → ②浏览器开 `http://127.0.0.1:<port>` → ③`check_harness.py --review`。AI 不经沙箱起长跑进程。

### 6.3 渲染口径（源程序渲染，后端与网页不懂游戏）

| 内容 | 渲染 |
|---|---|
| `form` | 照抄 `ConsoleReviewer._format_form`（pydantic → `model_dump_json(indent=2)`，其余 `str()`） |
| 机械结算 | 照抄 `ConsoleReviewer.audit()` 的四行头 |
| 模型裁决 | `done` + `why` |
| `events` | 每条一行 `ts · kind · source · step` + 截断的 content |

**抽出共用**：`ConsoleReviewer` 与 `WebReviewer` 的渲染挪进一个 `harness/review_render.py`，两者都调它，避免"照抄"变成两份漂移的拷贝。

### 6.4 实时 trace 与画面（0925 补）

**要什么**：网页不只在问人时亮一张表，平时也能实时看到 run 在干什么——包括画面。画面已经在 trace 里：`sense_frame` 事件的 `content.frame` 是 base64 PNG（`tools/trace/render.py`），一条事件一个 JSON 文件。

**怎么实时**：不让后端去盯 trace 目录（那是服务端轮询，还把后端绑到盘上路径），而是在**写账的那一刻顺手推**：

```
TraceTool.append → render → LiveFeedTrace.append ─┬─► LocalTrace.append（落盘，唯一真相，不变）
                                                  └─► 队列 → 后台线程 → WS /feed → 后端 → 广播 /ui
```

- `LiveFeedTrace`（`pokemon_agent/tools/trace/live_feed.py`）：`TracePort` 的装饰器，包在 `LocalTrace` 外面——它拿到的是**渲染好的事件**（type / kind / meta / content），不用重复渲染逻辑。`build.py` 只在 `--review` 时包上。
- **绝不拖慢、绝不拖垮 run**：`append` 只把事件丢进有界队列就返回；后台 daemon 线程负责发。队列满就丢最旧的；后端不在或断了就丢弃并只打一行日志。盘上的账不受任何影响。
- 信封：`FromHarnessToReviewBackendFeedReq{run_id, event}`、`FromReviewBackendToFrontendFeedReq{run_id, event}`，都无 Resp。
- 后端：不解析，原样转播；为重连补发保留最近 N 条（`deque`，N 取几百）。
- 网页：按 `kind` 分栏——`sense_frame` 的 `frame` 直接 `<img src="data:image/png;base64,…">` 当"当前画面"，其余事件进时间线；问人时，把被审对象（`meta.task_id` / `episode_id`）的帧挑出来并排显示（审 task 时看它的首帧与末帧）。
- 回放段（从存档恢复、还没到切换点）的事件不推：那段是重演，画面没意义，也会刷屏。
- 代价：网页要认识 trace 事件的形状（kind 与 content 的几个键）——展示层认识数据是应该的；后端仍然不认识。

**问人时网页收到什么**（与 §6.3 渲染对应）：

| 场合 | 网页上有什么 |
|---|---|
| 插话 · run plan | 说明 + `PlannerOutcome` 的 JSON（这一版目标表改动、why）+ 输入框（空 = 没意见） |
| 插话 · episode plan | 说明 + `Decomposition` 的 JSON（task 链、why）+ 当前画面 + 输入框 |
| 审 · 一局 / 一个 task 的结果 | 机械结算四行（裁定 / 依据 / 结论 / 计数）+ 被审对象的事件时间线 + 它的首末帧 + 认账 / 推翻 + 备注 |
| 审 · 模型裁决 | 模型判 `done` 与 `why` + 它依据的材料（局摘要 / task 记忆表）+ 当前画面 + 认账 / 推翻 + 备注 |

## 七、删除 / 改动清单

| 面 | 件 |
|---|---|
| 删 | `harness/file_reviewer.py`；`harness/__init__.py` 里它的导出与 docstring；`check_harness.py` 的 FileReviewer 接线（看门狗 30 分钟依据、`--review` 注释、懒 import、注入、打印）；残留 `.workbuddy/review_request.json` / `review_answer.txt`（删前问你） |
| 改 | Protocol、Null、Console；`reviewing.py`；`ReviewMark`；`TapeReviewer`；两层 `review_and_judge`；`JudgeReq`（删 `human_note`）+ judge prompt；`last_judge`：两层 state、`DecomposeReq` / `PlanOnceReq`、`decompose.py` / `run_plan.py` 与模板；`record_verdict` 加 `audit`；`Reviewer.audit` docstring；`AuditReq/Resp` 分文件；`schemas/harness/__init__.py` 导出 |
| 增 | `schemas/harness/domain/judge_feedback.py`、`harness/web_reviewer.py`、`harness/review_render.py`、`review_backend/`（3 文件）、跳 A 4 件、跳 B 4 件、`InjectResp`、`tools/trace/live_feed.py` + 两件 Feed 信封、`config.WEB_REVIEW_TIMEOUT`、测试 |
| 依赖 | `pyproject`：主依赖加 `websockets`；删 `api` 组（fastapi/uvicorn）与 dev 里的 `httpx`——全仓零 import（0925 grep 核过）；你本机 `uv sync` 重锁 |
| 文档 | `docs/spec/harness/SPEC.md` §六整节；`docs/spec/experiment/SPEC.md` 的 FileReviewer 处；DATAFLOW 若提到问人链路一并；AGENTS §十二 `schemas/frontend` 那段（需你批）；CHANGELOG 两条 |

## 八、风险与取舍

| 项 | 说明 |
|---|---|
| 30s 太短 | 网页上读一张 Decomposition + 打字可能不够；超时就是没意见，run 不受损。真机跑一次看，不够再调这一个常量 |
| faulthandler 噪音 | `check_harness.py` 定时打全栈，等人时栈顶是 socket `recv`——预期行为，不是卡死 |
| 双标签页 | 先答先得，后答 `ok=false`；其余标签收到 Settle 自动清屏 |
| 网页打字时刷新 | 丢草稿，重连后 pending 仍在，重打即可 |
| 后端残留占端口 | 清场时带上 `review_backend` 进程 |
| 不做 | 鉴权 / TLS（只绑回环）、多 run 并发、历史落盘、`form` 对象过线、结构化改表单 |

## 九、原待拍板项的结论（用户 0925："你来判断，我不信它的"）

| # | 结论 | 依据 |
|---|---|---|
| Q2 后端住哪 | **顶层 `pokemon_agent/review_backend/`**（v0 建议 harness/，不采纳） | 放 harness 下，`python -m` 会先跑 `harness/__init__.py` 拉起整张 run 图；后端零 harness 依赖 |
| Q5 插话带 events | **不加**（v0 建议加，不采纳） | plan 的依据是 planner 看到的上下文，不是 trace 事件流；塞 events 只是为了页面"一样厚"，没有判断用途。以后真需要再加字段 |
| Q6 中途断连 | **降级 + 醒目日志 + `answered=False`**（采纳并补一条） | 与超时同语义，run 不因前端设施崩溃作废；`answered` 让账上分得清 |
| Q7 超时 | **30s**（用户定） | — |
| Q8 删 `api` 组 | **删，连同 dev 的 `httpx`**（采纳并扩大） | 全仓零消费者；`websockets` 原本只是经 `uvicorn[standard]` 间接进锁，删组后改为显式主依赖 |

## 十、实施顺序

| 步 | 内容 | 依赖 |
|---|---|---|
| W1 | 信封层：`InjectResp`、`AuditResp` 分文件、`AuditVerdict` 挪 domain、`answered`、`AuditReq.outcome` 扩成员、跳 A/B 8 件、导出同步 | — |
| W2 | 落点规则：episode judge 插话 → 审（删重问循环与 `JudgeReq.human_note`）；run 补审裁决；Protocol / Null / Console / `reviewing.py` / `ReviewMark` / `TapeReviewer` 跟随；`review_render.py` 抽出；§4.6 裁决反馈回 plan；trace 字段（`answered` `wait_s` 审的 `form_kind`、`judge_verdict.audit`） | W1 |
| W3 | 后端 `review_backend/` + `config` 两个常量 + `pyproject` 依赖调整 | W1 |
| W4 | `WebReviewer` + `check_harness.py` 接线（`--review` 改接 Web） | W2 W3 |
| W4b | `LiveFeedTrace` + `/feed` + 网页时间线与画面 | W3 |
| W5 | 自测：起后端 → 脚本当源程序发 ask → 脚本当网页答 → 断言；超时、双连接拒绝、断连降级、重连补发；feed 在后端缺席时 run 不受影响 | W4 W4b |
| — | **你本机**：真机 `--review` 跑一次（人真在网页上答）；`check_checkpoint.py --record` 重录 | W5 |
| W6 | 删 `file_reviewer.py` 及残留 + spec 文档同步 | 真机后 |
| W7 | AGENTS（需批）+ CHANGELOG | W6 |
