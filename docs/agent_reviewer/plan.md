# Agent Reviewer plan —— 实施步骤卡与验收

> 流程位置：`card.md`（身份/契约/边界）→ `spec.md`（设计规范）→ **`plan.md`（本文件：步骤卡/测试/验收）** → 落码
> 状态：**实施中（A1–A6 已落码 + 测试绿，CHANGELOG 340；A7 真机三进程跑交用户本机；A8 文档同步已做）**（2026-09-29，对齐 `card.md` v3.4 / `spec.md` v3.4：agent 是**独立进程**、地址在 `.env` 的
> `AGENT_REVIEWER_URL`、走**跳 C（WS）**、deadline **前端控制**、agent 按 `seq` 持有对话状态、`transcript` 走增量 delta）。
>
> 进度：A1 ✅ / A2 ✅ / A3 ✅ / A4 ✅ / A5 ✅ / A6 ✅（45 测试绿，ruff 改动文件净）；A7 ⬜ 你本机三进程真机跑（二号铁律：AI 不拉起）；A8 ✅ CHANGELOG + docs 同步。

---

## 〇、目标与范围（一句话 + 不在范围）

**目标**：在现有 `review_backend` 之上叠加一个**独立进程**的视觉 LLM 复核席（`agent_reviewer`，
deepseek-flash V4.1 原生视觉）。harness 照旧发 `ask`、收 `answer`，不知道背后是人还是 AI；
后端把 AI 的结论经**跳 C WS** 收来、再经**新增的 `proposal` 推送**喂给网页聊天栏；人在聊天栏里看/改/
点「发给 AI」回灌；前端开关随时切「AI 接管 / 我来处理」，AI 模式到点没人接管就自动提交。

**不在范围（v1）**：自治 agent（工具/自停/自决）、给 agent 游戏状态或记忆、OCR 极小字、
历史回看、鉴权/TLS/多 run 并发、改 `Reviewer` 协议或六个落点、动 judge/verify。
与 `docs/web_reviewer/intent.md`（纯展示前端）**正交可并存**。

---

## 一、前置（落码前的必读 + 现状核对）

| 项 | 现状 | 落码前必须确认 |
|---|---|---|
| 跳 A（harness↔后端） | 已落地 W1–W5，信封在 `schemas/harness/communication/` | 不动 |
| 跳 B（后端↔前端） | 已落地，信封在 `schemas/review_backend/communication/` | 本方案改 3 处 + 新增 2 件 |
| 后端 `ReviewBackend` | `pokemon_agent/review_backend/backend.py`（含 `_ask`/`_to_ask`/`_settle`/`_feed`/`_latest_frame` 待加） | A3 改 |
| 前端 `page.py` | 单页，待答卡片已有，无聊天栏/开关/倒计时 | A4 改 |
| `WebReviewer` | `pokemon_agent/harness/web_reviewer.py`，`timeout` 必有值、`recv` 叠加 GRACE | A5 放开 `None` |
| `DeepSeekProvider` | `pokemon_agent/brain/providers.py`，纯文本路由 + 视觉分支 | A2 复制去 brain 依赖 |
| `.env` | 已加 `AGENT_REVIEWER_URL=ws://127.0.0.1:8770`（`.gitignore` 第 20 行已忽略） | A2/A3 读它 |
| `config.json` | **已删除**（用户纠正：agent 地址走 `.env`，非 config.json） | 不再引入 |

> 所有信封都带 `msg` 标签、`model_dump_json()` 走 WS 文本帧，与跳 A/跳 B 同构。
> `ProposedAnswer` / `AskReq` / `ChatTurn` **跨跳复用同一模型**，不新造重复定义。

---

## 二、实施步骤卡（A1–A8）

> 每卡含：**目标 / 改动文件 / 具体动作 / 验收 / 测试 / 依赖**。勾选顺序即依赖顺序。

### A1 — 信封（schemas）`[无依赖]` ✅ 已落码

- **目标**：把跳 B 的三处改动 + 两件新增，以及跳 C 的四件信封全部落地；`ProposedAnswer` 单源。
- **改动文件**：
  - `schemas/review_backend/communication/FromReviewBackendToFrontendAskReq.py`：`deadline: float` → `float | None`
  - `schemas/review_backend/communication/FromReviewBackendToFrontendSettleReq.py`：`by: Literal["human","timeout","harness_gone"]` → 加 `"agent"`
  - `schemas/review_backend/communication/FromFrontendToReviewBackendAnswerReq.py`：加 `by: Literal["human","agent"] = "human"`
  - 新增 `schemas/review_backend/communication/ProposedAnswer.py`：`text: str | None = None` / `verdict: AuditVerdict | None = None` / `note: str = ""`（**单源**，跳 B `proposal` 与跳 C `proposal` 共用）
  - 新增 `schemas/review_backend/communication/FromReviewBackendToFrontendProposalReq.py`：`msg="proposal"` `seq: int` `proposal: ProposedAnswer` `round: int`
  - 新增 `schemas/review_backend/communication/FromFrontendToReviewBackendDiscussReq.py`：`msg="discuss"` `seq: int` `text: str`
  - 新增包 `schemas/agent_reviewer/communication/`：`ChatTurn.py`（`role`/`text`）、`FromBackendToAgentReviewerSeedReq.py`（`seed`,`seq`,`ask: FromReviewBackendToFrontendAskReq`,`frame: str | None`）、`FromBackendToAgentReviewerTurnReq.py`（`turn`,`seq`,`delta: ChatTurn`,`frame: str | None`）、`FromBackendToAgentReviewerCloseReq.py`（`close`,`seq`）、`FromAgentReviewerToBackendProposalMsg.py`（`proposal`,`seq`,`proposal: ProposedAnswer`,`round: int`）、`__init__.py`（导出 + `MSG_*` 常量）
- **具体动作**：`AskReq` 直接作为跳 C `seed` 的 `ask` 字段（不另造）；`ChatTurn` 是跳 C `turn` 的 delta 类型；`ProposedAnswer` 仅在 `review_backend/communication` 定义一次，跳 C 的 `ProposalMsg` import 复用。
- **验收**：六个信封 `model_validate` ↔ `model_dump_json` 往返通过；`by`/`deadline` 取值正确；`ruff` 净。
- **测试**：`tests/agent_reviewer/test_agent_reviewer_envelopes.py` —— 每个信封构造 + 往返 + `msg` 取值断言。
- **依赖**：无。

### A2 — `agent_reviewer` 进程（provider + agent + server + 入口）`[依赖 A1]` ✅ 已落码

- **目标**：独立进程的视觉 LLM 复核席，WS 服务端收跳 C `seed/turn/close`，推 `proposal`。
- **改动文件**：`pokemon_agent/agent_reviewer/`
  - `provider.py`：从 `brain/providers.py` 复制 `LLMProvider` 协议 + `DeepSeekProvider`（**只留 DeepSeek**，删 Qwen/Ark/`provider_for`/`pack_images_grid`）；`complete`/`describe` 改为收裸字段（`describe(prompt, images: list[str]) -> DescribeResult{text,input_tokens,output_tokens,cached_tokens,reasoning_tokens}`），**去掉对 brain 数据模型的 import**；定值 `model="deepseek-flash"`、`temperature=0`、`timeout=20`、`thinking=False`、`multimodal=True`、`json_mode=False`；请求格式 OpenAI 兼容 `chat.completions`，`content` 用 `text`+`image_url` block，base64 走 `_png_data_uri` 同款 `data:image/png;base64,…`。
  - `agent.py`：`AgentReviewer`，`self._convs: dict[str, list[ChatTurn]]`；`seed(ask, frame)`（建该 seq 对话 + 全量渲染 + 调 `_call`）、`turn(seq, delta, frame)`（增量追加 + `_call`）、`close(seq)`（删除）；`_call` 拼 prompt→`describe(images=[frame])` 或 `complete`→异常返回空 `ProposedAnswer`；`_SYSTEM`/`_seed_user`/`_render`/`_parse`（审：认账/推翻+note；插话：恒空串）。
  - `server.py`：`websockets` 服务端，按 `msg` 分流调 `agent.seed/turn/close`，把 `_call` 结果包成 `ProposalMsg` 经同一 WS 推回。
  - `__main__.py`：读 `.env` → `AGENT_REVIEWER_URL` 解析 host/port（CLI `--host/--port` 可覆盖）起 server；**`DEEPSEEK_API_KEY` 缺失即 `RuntimeError` 当场停**。
  - `__init__.py`：导出 `AgentReviewer`。
- **验收**：`python -m pokemon_agent.agent_reviewer` 能起；用 `websockets` 客户端发一条 `seed`（带测试 `frame`），能收回 `proposal`；`DEEPSEEK_API_KEY` 缺失时报错退出；`ruff` 净；**零 `import brain`**。
- **测试**：
  - `tests/agent_reviewer/test_agent_reviewer_provider.py`：fake provider（不联网）确认 `describe` 接收 `(prompt, [frame])`、`complete` 接收 `prompt`；异常被吞、返回空。
  - `tests/agent_reviewer/test_agent_reviewer_agent.py`：`seed` 建对话并返回 `ProposedAnswer`；`turn` 追加 delta 后内容不同；`close` 释放；`_parse` 审「推翻+理由」「认账」、插话恒空。
- **依赖**：A1（信封）。

### A3 — 后端 `AgentClient` + `ReviewBackend` 改动 `[依赖 A1, A2]` ✅ 已落码

- **目标**：后端经跳 C 连 agent 进程；移除自身 self-timeout；收 agent 推回的 `proposal` 广播；`settle.by` 正确判定。
- **改动文件**：`pokemon_agent/review_backend/`
  - 新增 `agent_client.py`：`AgentClient`（WS 客户端），构造时读 `.env` 的 `AGENT_REVIEWER_URL` 尝试连；**连不上不抛、不崩**——记警告、置内部 `None`，降级为无 agent；提供 `seed(seq, ask, frame)` / `turn(seq, delta, frame)` / `close(seq)` 三发送方法；后台协程监听 agent 推回的 `proposal`，经回调（或 asyncio.Queue）交给 `ReviewBackend` 广播。
  - `backend.py`：
    - `__init__` 加 `agent_client: AgentClient | None = None`，存 `self._agent`。
    - 新增 `_latest_frame() -> str | None`：逆序扫 `_feed`，取第一条含 `content.frame` 的事件（只取该字段，不碰游戏语义）。
    - `_ask`：移除 `asyncio.wait(..., timeout=req.timeout_s)` → 改 `timeout=None`；`has_agent = self._agent is not None`；`deadline = (now+AI_COUNTDOWN) if has_agent else None`；`ask` 广播后若 `has_agent` 则 `self._agent.seed(seq, ask, frame)`（不阻塞）；settle 前 `self._agent.close(seq)`；`by` 来源 `answer_by`。
    - `_serve_ui` 的 `async for raw` 加 `if m.msg == "discuss": self._discuss(raw); continue`；`_discuss` 校验 `seq==pending` 且非空 → `self._agent.turn(seq, ChatTurn(role="human", text=...), frame)`；`agent is None` 丢弃打日志；同 seq 正在处理忽略后续。
    - 新增 `answer_by(ans)`：`ans is None` 或内容空 → `"timeout"`；否则 `ans.by`（`"human"/"agent"`）。
    - `_to_ask(seq, req, deadline)` 把 `deadline` 直写 `AskReq.deadline`。
  - `__main__.py`：读 `.env` 构造 `AgentClient`；`ReviewBackend(agent_client=...)`；`--no-agent` 跳过（保留原 30s 行为）。
- **验收**：后端带 agent 起、收到 `ask` 后能看到跳 C `seed` 发出、`proposal` 被广播为跳 B `ProposalReq`；`answer.by=="agent"` 时 `settle.by=="agent"`、`by=="human"` 时 `=="human"`、空框 → `"timeout"`；`timeout=None` 时人模式无限等；`.env` 缺失/agent 没起时后端不崩、以无 agent 运行；`ruff` 净。
- **测试**：`tests/review_backend/test_review_backend_agent.py`：起一个 **fake WS agent server**（回固定 `proposal`），`ReviewBackend` 收到 `ask` 后断言：跳 C `seed` 被调、`ProposalReq` 被广播、`discuss` 触发跳 C `turn`、settle `by` 三种分支、`close` 在 settle 后发出。
- **依赖**：A1（信封），A2（agent 进程；测试用 fake 不必真起）。

### A4 — 前端 `page.py` `[依赖 A1]` ✅ 已落码

- **目标**：聊天栏 + 结论框 + 模式开关 + 倒计时（仅 AI 模式）+ 发给 AI + settle 标签。前端不感知 agent 存在。
- **改动文件**：`pokemon_agent/review_backend/page.py`
  1. **模式开关**：待答卡片顶部加「AI 接管 / 我来处理」两按钮；`ask.deadline != null` → 默认高亮 AI，「null」→ 默认高亮人；随时点切，影响当前 pending + 未来，不重发 ask。
  2. **结论框**：`textarea#conclusion`，始终可见可编辑；`ProposalReq` 到达时填入（round 0 首填，round>0 更新）。
  3. **聊天栏**（最小实现：只读时间线）：列出每笔 `proposal`（round + 文本）与每笔 `discuss`（人话）。
  4. **倒计时仅 AI 模式**：`m.deadline != null` 且当前为 AI 模式 → **首个 `proposal`（round 0）到达才开始** 30s 倒计时；归零：框非空 → `answer({..., by:"agent"})`，空 → `answer({by:"timeout"})`；agent 始终无响应则倒计时不触发（退化为人决定）。
  5. **「发给 AI」按钮**：`ws.send({msg:"discuss", seq, text: 结论框内容})`；后端推回新 `proposal` 刷新结论框与聊天栏。
  6. **提交**：AI 模式倒计时自动提交；人模式人点「提交」→ `answer({..., by:"human"})`（框空则 `by` 仍 human、内容空 → 后端判 `timeout`）。
  7. **settle 标签**：`by` 映射加 `agent: "AI 答了"`。
- **验收**：浏览器手测（A7）——切 AI/人、看画面、收 proposal、倒计时自动提交、发给 AI 二次 proposal、人提交；AI 模式空框超时记 `timeout`。逻辑 review + `ruff` 净。
- **测试**：前端以手测为主；可加 `tests/test_page_proposal.js`/或纯逻辑断言（若抽出了纯函数）。
- **依赖**：A1（信封字段）。

### A5 — harness `WebReviewer` + `check_harness` `[依赖 A3, A4]` ✅ 已落码

- **目标**：放开 `timeout=None`；`--review` 默认交 agent 计时，`--no-agent` 保留 30s 原行为。
- **改动文件**：`pokemon_agent/harness/web_reviewer.py`、`experiment/real_check/check_harness.py`
  - `web_reviewer.py`：`__init__(timeout: float | None = WEB_REVIEW_TIMEOUT)`（去 `assert timeout > 0`）；`_exchange` 的 `recv(self._timeout + GRACE_S)` 改 `recv(self._timeout)`（`None` 即阻塞，GRACE 无意义）；组跳 A 信封仍带 `timeout_s=self._timeout`（`None` 照传，后端忽略）。
  - `check_harness.py`：`--review` → `WebReviewer(timeout=None)`；`--no-agent`（或后端无 agent）路径 → `WebReviewer(timeout=WEB_REVIEW_TIMEOUT)`。
- **验收**：`WebReviewer(timeout=None)` 能构造、`recv(None)` 阻塞到后端 settle；`--review` 时 harness 不自带超时；`ruff` 净。
- **测试**：`tests/harness/review/test_web_reviewer_timeout_none.py`：构造 `WebReviewer(timeout=None)`、mock conn 断言 `recv(None)` 被调用、不叠加 GRACE。
- **依赖**：A3（后端不再自管超时）、A4（前端接管计时）。

### A6 — 测试与 `ruff` `[依赖 A2, A3, A4, A5]` ✅ 已落码（45 测试绿，ruff 改动文件净）

- **目标**：单元 + 集成覆盖，全部绿；`ruff` 净。
- **动作**：补齐 A1–A5 各卡的测试；`ruff check pokemon_agent tests` 全净；跑现有定向（`test_review_backend`/`test_review_points`/`test_review_render`/`test_build`/`test_node_io`/`test_web_reviewer*`）确认无回归。
- **验收**：所有新增测试绿；`ruff` 净；既有 reviewer 相关定向绿（spec §十.4）。

### A7 — 你本机三进程真机跑 `[依赖 A6]` ⬜ 待你本机（二号铁律：AI 不拉起长跑进程）

- **目标**：端到端验证人在网页上切 AI/人、看画面、发 discuss、自动提交。
- **顺序（AI 不经沙箱起长跑，二号铁律）**：
  1. `python -m pokemon_agent.agent_reviewer`（起 agent 进程，读 `.env` 绑地址）
  2. `python -m pokemon_agent.review_backend`（起后端，读 `.env` 连 agent）
  3. 开网页；`check_harness.py --review`（WebReviewer 仍走 `/harness`，不变）
- **验收**：网页在动、盘上账逐条同序、每个 pending 首笔 `proposal` 到达、AI 模式 30s 自动提交 `by=agent`、人模式无倒计时人提交 `by=human`、空框自动发 `by=timeout`、发给 AI 二次 proposal、`close` 清 seq。

### A8 — CHANGELOG + docs 同步 `[依赖 A6，文档侧现已完成]` ✅ 已做

- **目标**：留痕 + 文档与代码对齐。
- **动作**：`CHANGELOG.md` 加一条（倒序，四段：改了什么/为什么/取舍/影响面）✅（340）；`spec.md` 状态由「讨论稿」转「已实施」✅；`docs/web_reviewer/plan.md` 本就是 agent 前置设施、无独立 agent 条目可收，已在其进度块加一笔指向 `docs/agent_reviewer/`；`AGENTS.md` ✅ 已补——§十二 分包形态段加 `schemas/review_backend/communication/`（跳 B）+ `schemas/agent_reviewer/communication/`（跳 C）信封说明（`ProposedAnswer` 单源、`by` 字面量含 `timeout`、`deadline` 可 `None`），§四 目录树加 `review_backend/` 与 `agent_reviewer/` 两个顶层包（与 web_reviewer W7「需你批文字」同口径，已批已补）。
- **验收**：CHANGELOG 条目与代码改动对应；docs 与代码一致。

---

## 三、测试清单（汇总）

| 测试文件（新增） | 覆盖 | 类型 |
|---|---|---|
| `tests/agent_reviewer/test_agent_reviewer_envelopes.py` | A1 六件信封构造/往返/`msg`/`by`/`deadline` | 单元 |
| `tests/agent_reviewer/test_agent_reviewer_provider.py` | A2 provider 收裸字段、异常吞空、零 brain import | 单元（fake） |
| `tests/agent_reviewer/test_agent_reviewer_agent.py` | A2 seed/turn/close 状态、`_parse` 审/插话 | 单元（fake） |
| `tests/review_backend/test_review_backend_agent.py` | A3 后端经跳 C seed→proposal 广播、discuss→turn、settle by 三分支、close | 集成（fake WS agent） |
| `tests/harness/review/test_web_reviewer_timeout_none.py` | A5 `WebReviewer(timeout=None)` 构造/recv(None)/无 GRACE | 单元 |
| 前端 `page.py` 手测 | A4 模式切换/结论框/倒计时/发给 AI/settle 标签 | 手测 |

> 既有定向（review_backend / review_points / review_render / build / node_io / web_reviewer）在 A6 须无回归。

---

## 四、验收总条（来自 spec §十，机械可验）

1. 带 agent 起后端 + `check_harness --review`：网页在动，盘上账与不带 agent 时逐条同序；每个 pending 首笔 `proposal` 到达后聊天栏出现 AI 结论；AI 模式 30s 自动提交且 `by=agent`；人模式无倒计时、人提交 `by=human`；空框自动发记 `by=timeout`。
2. 「发给 AI」：点一次 → 后端 agent `turn` 被调、新 `proposal` 推回、结论框更新、`close` 在 settle 后清掉该 `seq`。
3. 后端不在（未起）：run 照跑完，只打一行降级日志，`answered=False`。
4. `ruff` + 定向测试绿（A6）。

---

## 五、风险与回滚

| 风险 | 缓解 |
|---|---|
| AI 模式 agent 慢（≤20s）与倒计时赛跑 | 倒计时从首个 `proposal` 到达才开始；agent 始终不响应则退化为人决定（spec §十二） |
| 前端倒计时是信任边界 | 后端不强制；人改框手动提交可覆盖；run 有 watchdog 兜底 |
| agent 独立进程需起需连 | `.env` 缺失/`AGENT_REVIEWER_URL` 错 → 后端降级为无 agent（不崩）；agent 崩不伤 run，只服务新 seq |
| 改动面跨界（schemas/后端/前端/harness） | A1–A5 各步独立可勾选；每步带定向测试；`--no-agent` 保留纯人路径，可随时回退到 W5 行为 |
| 模型误判 | `_parse` 取不到明确词默认 ACCEPT（误判"没成"代价小）；真机 A7 观察，必要时加 `json_mode` 或收紧 prompt |

**回滚**：任一中间步出问题，保留 `--no-agent` 路径即可回退到「纯人 + 后端自管 30s」原状（W5 行为），不阻塞 run。
