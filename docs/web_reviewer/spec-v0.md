> 状态：旧实现已在 reviewer R6c（523）删除；当前入口为 `python -m pokemon_agent.reviewer --seats human`。新 AI 席待 R7。以下正文作为历史设计保留。

# PLAN_web_reviewer —— 人在环第三实现：独立后端 + 前端页面（WebSocket 推送）

> 用户 0925 三轮口径（10:2x / 10:4x / 10:5x），全部已并入本文：
> ①做前端、删 FileReviewer；②三方通信（源程序 + **独立后端** + 前端），**后端推给前端，不轮询**；
> ③**AI 不再是驱动方**；④**每个信封都必须成对（Req+Resp）**，采纳新命名，旧信封一并修；
> ⑤**审只在 `review_and_judge` 格、插话只在 plan 格**（现状里 `JudgeVerdict` 那处插话违反这条，改）；
> ⑥**用 WebSocket**（`websockets` 库，不手写帧）。
> 本文是设计，不含实现。
>
> 前置阅读：`PLAN_console_reviewer.md`（插话/审为什么是这两个方法）、`AGENTS.md` §十二（信封命名定稿）、
> `docs/spec/harness/SPEC.md` §六（人在环现状）。

---

## 0. 一句话结论

把「人」从**一对文件**（`.workbuddy/review_request.json` ↔ `review_answer.txt`）换成**一个常驻后端 + 一个页面**：

```
     ① HTTP POST（阻塞，等答案）              ② WebSocket 推送
源程序 ──────────────────► 后端 ──────────────────► 前端（浏览器）
（run 进程内         ◄─── ③ 回执（HTTP 响应） ◄─── ④ 回话（同一条 WS 连接）
  WebReviewer）
```

源程序侧只多一个 **HTTP 客户端**（`Reviewer` 的第三个实现），后端是一个**独立常驻进程**，前端是后端吐出的单页。
信封**全部成对**、**每跳点名两端**；落点规则收成一句：**插话只在 plan 格，审只在 `review_and_judge` 格**。

---

## 1. 为什么换掉 FileReviewer

三条独立的病，前两条是功能性的，第三条是复杂度成本：

| # | 病 | 证据 |
|---|---|---|
| 1 | **请求里没有内容** | `file_reviewer.py:162-172` 只落 `{form_kind, prompt, ts}`，form 本体故意不落盘。**页面上没法显示"在审什么"**——而这正是做前端的唯一理由 |
| 2 | **回话只有一个字符串** | `review_answer.txt` 非空 = 插话、空 = 没意见。**审走不到**：`FileReviewer.audit()` 恒认账（`:196`），`docs/spec/harness/SPEC.md:134` 列为"已知缺口" |
| 3 | **文件握手的全部复杂度** | mtime 判新鲜、**零删除协议**（`:17-30`：沙箱单回合删除硬闸实测掐死过进程）、原子 `tmp+rename`——全是为绕过"没有共享内存"，没有一件服务"人机对话"本身 |

---

## 2. 三方架构

| 方 | 是谁 | 住哪 | 生命周期 |
|---|---|---|---|
| **源程序** | run 进程内的 `WebReviewer`（`Reviewer` 第三实现，HTTP 客户端） | `pokemon_agent/harness/web_reviewer.py` | 一次 run |
| **后端** | 持待答问 + WS 广播 + 收答 + 回执的本地服务 | `pokemon_agent/harness/review_backend/`（Q2） | **常驻**，跨多次 run |
| **前端** | 后端 `GET /` 吐出的单页（人在这里答） | 后端内联（`page.py`） | 随开随关 |

**边界**：源程序不认识前端（只知道后端 URL）；前端不认识源程序（只见推来的 ask）；后端不知道任何游戏语义
（只搬"渲染好的文本 + 事件行"，渲染口径 §6.3）。**源程序侧仍然阻塞**——图停在节点内部等人
（`PLAN_console_reviewer.md` §2 不变），落地是**长挂 HTTP POST**。

**拆出后端的收益**：run 进程零服务端代码；页面可先开、跨 run 复用；前端崩了 run 照跑（超时降级）；
`curl` 就能看/答。**代价**：多起一个进程（起跑两条命令）；多一跳、多两组信封。

---

## 3. 信封：全部成对 + 每跳点名两端

### 3.1 现状的账（哪些要改）

| # | 现状 | 判定 | 处置 |
|---|---|---|---|
| a | `inject(req) -> str`，**没有 Resp** | 规则的字面结果（§十二第 1 条"返回结构化载荷才有 Resp"，`str` 是标量）——但**这条规则在这里站不住**：回话有语义（空串 = 没意见），类型系统却看不见 | **补 `FromHarnessToReviewerInjectResp{text}`**，Protocol 改为 `inject(req) -> FromHarnessToReviewerInjectResp` |
| b | `AuditResp` + `AuditVerdict` 与 `AuditReq` 挤一个文件 | **违规**：`communication/` 下其余 12 组 Req/Resp 都是一文件一个类 | `AuditResp` 分文件；`AuditVerdict` 挪 `schemas/harness/domain/audit_verdict.py`（三类信封共用它） |
| c | `...AuditResp` 名字仍是 `FromHarnessToReviewer`（数据往回走） | 不违规（口径：Resp 沿用发起方方向名 + 两半放发起方，先例 `FromHarnessToBrainToolChooseOnceResp`） | 不改 |
| d | `FromHarnessToGameToolResetReq` 无 Resp | 不违规（返回 `None` 的先例） | 不改；**推送给前端同理无 Resp**（单向通知，不是请求） |

### 3.2 新信封总表（新增 7 件 + 修 3 件）

**进程内（harness ↔ Reviewer 实现，现状那一跳）**

| 信封 | 方向 | 字段 | 状态 |
|---|---|---|---|
| `FromHarnessToReviewerInjectReq` | harness → 实现 | `prompt` `form` `form_kind` | 已有，不动 |
| `FromHarnessToReviewerInjectResp` | 实现 → harness | `text` | **新增** |
| `FromHarnessToReviewerAuditReq` | harness → 实现 | `run_id` `episode_id` `task_id?` `outcome` `events` | 已有，`outcome` 扩成员（§4） |
| `FromHarnessToReviewerAuditResp` | 实现 → harness | `verdict` `note` | 已有，**分文件** |

**跳 A（源程序 ↔ 后端，HTTP）**

| 信封 | 方向 | 字段 |
|---|---|---|
| `FromHarnessToReviewBackendInjectReq` | 源程序 → 后端 | `seq` `run_id` `prompt` `form_kind` `form_text` |
| `FromReviewBackendToHarnessInjectResp` | 后端 → 源程序 | `text` |
| `FromHarnessToReviewBackendAuditReq` | 源程序 → 后端 | `seq` `run_id` `episode_id` `task_id?` `prompt` `outcome_text` `events: list[str]` |
| `FromReviewBackendToHarnessAuditResp` | 后端 → 源程序 | `verdict: AuditVerdict` `note` |

**跳 B（后端 ↔ 前端，WebSocket）**

| 信封 | 方向 | 字段 |
|---|---|---|
| `FromReviewBackendToFrontendAskPush` | 后端 → 前端 | `seq` `run_id` `kind`（`inject`/`audit`）+ 上面两条 Req 的展示字段（按 kind 二选一）。**推送无 Resp**（同 `d`） |
| `FromFrontendToReviewBackendAnswerReq` | 前端 → 后端 | `seq` `text?`（插话）`verdict?` `note?`（审） |
| `FromFrontendToReviewBackendAnswerResp` | 后端 → 前端 | `seq` `ok` `reason`（回执：409 的两种情况在这里变成 `ok=false`） |

跳 A / 跳 B 字段同构不是冗余：同一份内容、两个"谁产出谁消费"的场合，按两端分家——与 `ModelCall`
两份同款的既有口径一致（`AGENTS.md` §十二第 4 条）。**`form` 本体（Python 对象）不出进程**：线上一律是
源程序渲染好的 `form_text`；`form_kind` 随行（它本来就是 `InjectReq` 上的一个**类型标签字符串**，
渲染与复盘用——源程序用它挑渲染分支，后端/前端不解释它）。

---

## 4. 落点规则：插话只在 plan 格，审只在 `review_and_judge` 格

### 4.1 现状违反这条规则的地方

现状五处调用点里，**`episode/review_and_judge:74` 的 `JudgeVerdict` 插话不合规**：它亮给人的是
`{done, why}` —— 一个**单一结论**，按判据（`PLAN_console_reviewer.md` §2：单一结论 → 审）它**本该是审**，
现在却用"插话 + 带话重问"实现。同格的 `:113`（审 task 定案）反而是合规的。

### 4.2 改成什么

| 层 | plan 格：插话 | `review_and_judge` 格：审 |
|---|---|---|
| **run** | `PlannerOutcome`（`plan_run:94`，不动） | ①审刚跑完那一局（`:133`，不动）②**补**：审模型对 `run_goal` 的裁决（现在零人窗口） |
| **episode** | `Decomposition`（`plan_episode:98`，不动） | ①审刚定案的 task（`:113`，不动）②**改**：`:74` 的 `JudgeVerdict` 插话 → 审本局裁决 |
| **task** | 无（一圈=一个键，刻意，见 4.4） | 无（同左） |

**新调用点：插话 2 处（都在 plan）、审 4 处（都在 review_and_judge）——两层完全同构。**

### 4.3 "审裁决"的机制细节

- **被审对象扩成两类**：`AuditReq.outcome: EpisodeOutput | TaskOutput` → 加成员
  `FromHarnessToBrainToolJudgeResp{done, why, …}`（模型裁决）。一个信封、一次 `audit()` 调用，
  页面按成员渲染（"机械结算" / "模型裁决"两副面孔）。
- **推翻的机械映射**（`AuditVerdict.OVERTURN` 落到哪，全由 harness 盖章，人不写状态）：

  | 审点 | OVERTURN 的后果 |
  |---|---|
  | run · 审一局 | 盖反面（`COMPLETED`↔`FAILED`）、`overturned=True`、修正 `fail_streak`（现状） |
  | episode · 审一个 task | 同上（现状） |
  | run · 审裁决 | `GOAL_DONE` 作废 → `termination` 回机械三类的结论，run 继续跑 |
  | episode · 审裁决 | `GOAL_DONE` 作废 → 本局继续跑下一个 task |

- **行为变化（要认账）**：`human_note` 的"带话重问"循环**删除**——重问 LLM 是插话的语义，
  审不重问；人的 `note` 仍落 `record_verdict(human_note=…)`（字段现成），供复盘与下一轮 plan 参考。
  实测含义：以前人可以说"步数用尽不算达成"让模型改口，现在人直接表态翻转，模型没有第二次机会。
- **`FromHarnessToBrainToolJudgeReq.human_note` 字段保留**（plan 侧插话仍走它），但 judge 链路上的
  "human_note 非空 → prompt 末尾拼接"这段随之只剩 task 层 `allow_interrupt` 的余用——实施时核对 prompt
  模板，无引用则一并清。

### 4.4 task 层零人在环 = 刻意例外（写明，不留悬案）

task 层一圈 = 一个键。逐键问人会让人退化成"每键点一下的打分机"，人在环的价值（对拆解与判定做高层纠正）
反而被淹掉。这条之前没有文档依据，本节把它写进 spec 作为定案。

---

## 5. 通信协议

### 5.1 端点（后端）

| 端点 | 通道 | 谁调 | 语义 |
|---|---|---|---|
| `GET /` | HTTP | 前端 | 单页 `PAGE_HTML` |
| `GET /health` | HTTP | 源程序（构造探活）/ 人 | `{ok, port, pending_seq}` |
| `POST /review/inject` | HTTP | 源程序 | body = 跳 A InjectReq，**长挂**，答出即回 InjectResp |
| `POST /review/audit` | HTTP | 源程序 | body = 跳 A AuditReq，**长挂**，答出即回 AuditResp |
| `/ws` | **WebSocket** | 前端 | 推送 + 回话（双向）：连上先补发当前 pending 快照与最近历史；此后服务端推 `AskPush`、客户端发 `AnswerReq`、服务端回 `AnswerResp` |
| `POST /review/answer` | HTTP | 脚本 / 调试兜底 | body = 跳 B AnswerReq；与 WS 回话等价，后端按 `seq` 幂等（重复 → 409 / `ok=false`） |

`seq` 全局单调（不随 run 重置）；`run_id` 由源程序 `WebReviewer(run_id=…)` 构造参数给（`inject` 信封本身
没有 run_id，统一由构造参数补齐，不让"有的有有的没有"）。

**两条源程序侧约定**：图是串行的 → 一次只挂一个 ask，后端收到第二个未答完的 ask → 409 + 醒目日志
（不当 assert：跨进程输入不是"调用方"）；长挂超时由**源程序侧先走**（client timeout = `REVIEW_TIMEOUT + 5s`，
后端 handler 更宽）。

### 5.2 WebSocket：为什么从"不用"改成"用"

0925 10:4x 我曾建议 SSE，理由是"标准库没有 WS 服务端"。**用户 10:5x 定：用 WebSocket。** 采纳，理由记账：

1. **零依赖约束被高估了**——项目本就要 `uv sync`，加一个 `websockets`（纯 Python、无 C 扩展）成本是一次同步；
2. **双向在这里有了真用处**：前端回话与推送走**同一条连接**（`AnswerReq`/`AnswerResp` 成对了，
   SSE 方案下回执是 HTTP 另一跳，反而别扭）；
3. 前端以后要做更复杂的事（结构化改表单、暂停/继续控制）天然有通道。

**实现形态（不手写 RFC 6455 帧）**：`pyproject.toml` 依赖加 `websockets`；
后端进程 = `ThreadingHTTPServer`（页面 / health / 源程序两条长挂 POST）+ 一个 **daemon 线程跑 asyncio 事件循环**
里的 `websockets.serve()`（推送与回话）。两台服务器共享同一个后端状态对象（锁内读写 `seq`/`_pending`）。

### 5.3 超时与降级

| 情形 | 行为 |
|---|---|
| 人答了 | 正常返回 |
| 人没答 / 前端没开 | 到 `REVIEW_TIMEOUT` → 插话回 `text=""`（没意见）、审回 `ACCEPT`（认账）——**与 Console/File 两实现逐字同语义**；同时推一条「第 N 问已超时作废」给前端 |
| 后端连不上（构造探活失败） | **抛 `OSError` 当场停**：宁可在装配时炸，别等一局跑完才发现没人能接 |
| 长挂中途后端死了 | 建议**降级 + 醒目日志**（`[review] 后端断连，第 N 问按没意见处理`），run 不因前端基础设施崩掉而整局作废（**Q6**） |

---

## 6. 源程序侧与后端

### 6.1 `WebReviewer`（`pokemon_agent/harness/web_reviewer.py`）

标准库 `urllib.request` + `json`，零第三方。构造即 `GET /health` 探活，失败抛 `OSError`。
`inject`/`audit` = 渲染 → 组信封 → 长挂 POST → 取 Resp 字段。渲染照抄既有口径（§6.3），
实现不认识 `form_kind` 的语义。每问每答一行 `[review]` 日志（沿用"信箱动态全在 stdout"口径）。
不做：不起服务、不存状态、不重试。

### 6.2 后端（`pokemon_agent/harness/review_backend/`）

```
pokemon_agent/harness/review_backend/
    __init__.py    ReviewBackend：状态机 + HTTP 路由 + WS 广播
    page.py        PAGE_HTML 常量（单页内联）
    __main__.py    python -m pokemon_agent.harness.review_backend
```

住 `harness/` 的理由：它是 `Reviewer` 这个 harness Port 的"人那一端"，与 `console_reviewer.py`
（绑 stdin/stdout）同一性质；只 import `schemas/`，不碰 tools/brain/world/memory（**Q2**，备选：顶层并列）。

**状态机**：`ask` 到达 → 已有未答 ask 则 409；`seq += 1`、挂 `_pending`、WS 广播 `AskPush` →
`Event.wait(超时)` → 人答则回执 = 人的答案，超时则回执 = 默认 + 广播"已作废" → 清 pending、
追加历史（内存 `deque(maxlen=50)`，不落盘——定案账在 trace 的 `settle_*.audit` / `human_note` 里）。
前端连上/重连：补发 pending + 历史，**零轮询**。服务：绑 `127.0.0.1`，端口**固定**（`config.REVIEW_BACKEND_PORT`），
被占**报错退出**（提示"上次的后端还在跑？"），不自动挪——三方都靠这个端口找人。

**生命周期**：后端由**你本机**起（`python -m pokemon_agent.harness.review_backend`）——与二号铁律一致，
AI 不经沙箱起长跑进程；AI 清场时只杀命令行命中的 `review_backend` / `check_harness`。
起跑顺序：①后端 → ②页面开 `http://127.0.0.1:8765` → ③`--review` 起 run。

### 6.3 渲染口径（源程序渲染一次，后端与前端零语义知识）

| 内容 | 怎么渲染 | 出处 |
|---|---|---|
| `form` | `model_dump_json(indent=2)`，其余 `str()` | 照抄 `ConsoleReviewer._format_form` |
| `outcome` / 裁决 | 机械结算四行（裁定/依据/结论/计数）照抄 `ConsoleReviewer.audit()` header；模型裁决渲染 `{done, why}` | 两副面孔按 `outcome` 成员分流 |
| `events` | 每条一行：`ts · kind · source · step` + content 截断 | `meta` JSON 解不动的事件跳过（同 `run/review_and_judge._meta_episode_id`） |

---

## 7. 删除清单（FileReviewer + 旧协议的完整账单）

| 面 | 件 |
|---|---|
| **代码·删** | `pokemon_agent/harness/file_reviewer.py`；`harness/__init__.py` 三实现那行与 docstring；`check_harness.py` 六处（`:141-142` 看门狗依据、`:158-161` 注释、`:181`、`:274-277` 懒 import、`:319-322` 注入、`:336` 打印）；残留 `.workbuddy/review_request.json` + `review_answer.txt` |
| **代码·改** | Protocol（`inject` 返回 Resp）；`NullReviewer` / `ConsoleReviewer` 签名跟随；`episode/review_and_judge`（JudgeVerdict 插话 → 审裁决 + 删重问循环）；`run/review_and_judge`（judge 补审裁决）；`FromHarnessToReviewerAuditReq.outcome` 加成员；`AuditResp` 分文件、`AuditVerdict` 挪 domain；`schemas/harness/__init__.py` 导出同步 |
| **代码·增** | `web_reviewer.py`、`review_backend/`（3 文件）、7 个新信封（§3.2）、`config.REVIEW_BACKEND_*` 常量、`pyproject` 加 `websockets`、测试 |
| **文档** | `docs/spec/harness/SPEC.md`（`:25` 目录树、`:109-120` §六整节重写——实现表、**插话点/审点那张过期清单**、§八缺口消失）；`docs/spec/experiment/SPEC.md`（`:91`、`:113`、`:137`） |
| **记忆** | `MEMORY-review.md` 整篇重写（信箱协议/守望器全作废）；`MEMORY-harness.md:26-27`、`MEMORY-trace.md:74`、`MEMORY.md:8` 索引行 |
| **skill** | `pokemon-realcheck-inloop` **已删**（0925 用户口径"直接删了吧，是老东西"；AI 驱动方角色撤销后整套流程作废） |
| **CHANGELOG** | 建议两条：①落点规则收口 + 信封成对（协议改动）；②WebReviewer + 后端 + 删 FileReviewer |

---

## 8. 风险与取舍

| 项 | 说明 |
|---|---|
| 端口被占 | 固定端口 + 占用即退出（三方都靠端口找人，不能自动挪） |
| faulthandler 噪音 | `check_harness.py:98` 每 4 分钟打全栈，等人时栈顶是 socket 读——**预期行为不是卡死** |
| 长挂 HTTP 被掐断 | 只走回环无代理，超时由源程序侧先走（§5.1） |
| 前端断开/双标签 | 后端留 pending 等重连；先答先得、后答 `ok=false`；其余标签页收到广播自动清屏。人正打字时页面崩会丢那一问（提交失败重试提示，页面侧小事） |
| 后端残留占端口 | 清场要带上 `review_backend` 进程 |
| 删"带话重问"循环 | 行为变化（§4.3）：模型失去改口机会，人直接翻转。判停语义因此**更机械**——与"判定只认达成"的既有口径同向 |
| 不做的事 | 鉴权与 TLS（回环 + 单 run）、多 run 并发（后端串行）、静态资源目录（页面内联）、`form` 对象过线（只送文本）、历史落盘（trace 已有账） |

---

## 9. 待拍板

| # | 问题 | 我的建议 |
|---|---|---|
| **Q2** | 后端住哪：`pokemon_agent/harness/review_backend/` 还是顶层并列 | 放 `harness/`（`Reviewer` 的"人那一端"） |
| **Q5** | 插话侧要不要补 `events`（审有、插话没有，页面一厚一薄） | **加**（`InjectReq` 加 1 字段 + 2 个 plan 调用点各塞一行，手里都有 trace 端口） |
| **Q6** | 长挂中途后端断连：降级（run 照跑）还是上抛（当场停） | **降级 + 醒目日志** |
| **Q7** | `REVIEW_TIMEOUT` = 300s 是否沿用 | 沿用，跑一次真机看实际等待再定 |
| **Q8** | `pyproject` 的 `api = [fastapi, uvicorn]` 组（注释"等拍板定夺"） | **删**（本设计用的是 `websockets`，fastapi/uvicorn 彻底没有消费者） |

已定不再列：信封全成对（§3）、新命名（§3.2）、落点规则（§4）、WebSocket + `websockets` 库（§5.2）。

---

## 10. 实施顺序

| 步 | 内容 | 依赖 |
|---|---|---|
| **W1** | 信封层：7 个新信封、`InjectResp`、`AuditResp` 分文件、`AuditVerdict` 挪 domain、`AuditReq.outcome` 扩成员、导出同步 | 无 |
| **W2** | 落点规则：`episode/review_and_judge` JudgeVerdict 插话 → 审裁决（删重问循环）；`run/review_and_judge` 补审裁决；`Null`/`Console` 两实现签名跟随 | W1 |
| **W3** | 后端：`review_backend/`（HTTP + WS + 页面）+ `config` 常量 + `pyproject` 加 `websockets` | W1 |
| **W4** | 源程序侧：`WebReviewer` + `check_harness.py` 接线 | W3 |
| **W5** | 自测：起后端 → 脚本 POST 假 ask → 浏览器 WS 答 → 断言回执；超时降级；409 三态；重连补发 | W1–W4 |
| **W6** | 删 `file_reviewer.py` + 残留 + `docs/spec/*` 同步 | W5 |
| **W7** | 记忆重写 + CHANGELOG 两条 | W1–W6 |

**一次真机 run 排在 W5 之后、W6 之前**：先拿真链路验"人真的能在页面上答上话"，再删旧实现。
