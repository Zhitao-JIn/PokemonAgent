> 状态：旧实现已在 reviewer R6c（529）删除；当前入口为 `python -m pokemon_agent.reviewer --seats human`。新 AI 席待 R7。以下正文作为历史设计保留。

# Agent Reviewer spec —— 独立进程内的视觉 LLM 复核席，与人在同一个聊天栏里磨结论

> 状态：**已实施 v3.4**（2026-09-29，基于 `card.md` v3.4：agent 是独立进程、地址在 `.env` 的
> `AGENT_REVIEWER_URL`、走跳 C WS、deadline 前端控制）。代码已落（A1–A6，CHANGELOG 340），
> A7 真机三进程跑交用户本机。本文是设计规范，实施顺序见 §十一，plan 另写 `plan.md`。
>
> **前置文档**：`docs/web_reviewer/spec.md`（现有设施，本方案在其上叠加）、
> `docs/agent_reviewer/card.md`（身份 / 契约 / 边界 / 判据）。
> **核心结论（card 已定）**：agent 是**独立进程**里的有状态视觉 LLM 复核席
> （deepseek-flash V4.1 原生视觉），不是 `Reviewer` 的第五个实现、不进 harness 进程、也不进后端进程；
> harness 六个落点、`Reviewer` 协议、跳 A 信封**全不动**；deadline 由**前端控制**；
> transcript 由 agent 按 `seq` 持有（在 agent 进程内存），后端只经**跳 C WS**发增量 delta；
> agent 地址写在 `.env` 的 `AGENT_REVIEWER_URL`，后端起时连、连不上降级为无 agent。

---

## 〇、相对 card v3.2 的更正 / 细化（核过代码，已并入 v3.4）

| # | card 的说法 | 实际 / 修正 | 处置 |
|---|---|---|---|
| 1 | "answer 信封不变" | 后端要区分"前端自动提交（agent）"与"人手动提交（human）"，否则 `by` 只能猜；空框自动发还要能记成 `timeout` | `AnswerReq` 加可选 `by: Literal["human","agent"] = "human"`；后端按 `by` + 内容空否判定 |
| 2 | 没写 harness 超时归属 | 当前 `_ask` 用 `asyncio.wait(..., timeout=req.timeout_s)` 自管超时；`WebReviewer.recv(timeout_s+5)` 也掐表 | **后端移除自身 self-timeout**；`WebReviewer` 收 `timeout=None`（阻塞至后端 settle）；计时完全交给前端倒计时 + run watchdog |
| 3 | 没写 agent 怎么拿帧 | 后端 `_feed` 是 JSON 字符串 deque，当前不解析 | 后端新增 `_latest_frame()`：逆序扫 `_feed`，取第一条含 `content.frame` 的事件（轻量，只取该字段，不碰游戏语义） |
| 4 | `propose_first/turn` 只写签名 | 具体 prompt 结构与解析没给 | 本节 §5.3 / §5.4 给 |
| 5 | `AskReq.deadline: float` | 人模式要传 `None`（无倒计时） | 改 `float \| None`；`_to_ask` 按 agent 是否存在决定 |
| 6 | 纯展示 intent 正交 | 仍成立；本方案不动 `--feed-url` 那条线 | 纯展示 = 关问人只推 feed；本方案 = 换掉应答方 |

---

## 一、一句话结论

在现有 `review_backend` 里塞一个**有状态的视觉 LLM 复核席**（`AgentReviewer`，deepseek-flash）。
它坐在后端 `/ui` 这侧：harness 照旧发 `ask`、收 `answer`，不知道背后是人或 AI；后端把 AI 的结论
通过一笔**新增的 `proposal` 推送**喂给网页聊天栏；人在聊天栏里看 / 改 / 点「发给 AI」回灌；
前端一个开关随时切「AI 接管 / 我来处理」，AI 模式到点没被接管就自动提交。

```
harness(WebReviewer) ──WS /harness──► 后端 ──┬─ 跳C WS ─► agent_reviewer 进程（deepseek-flash 视觉，独立进程，地址见 .env 的 AGENT_REVIEWER_URL）
                                            ├─ 新增 proposal 推送 ──WS /ui──► 浏览器（聊天栏 + 结论框 + 开关）
                                            └─ 收 answer/discuss ──► 翻跳 A Resp ──► harness
```

## 二、端点与角色（沿用 web_reviewer spec §5，新增一笔）

| 路径 | 谁连 | 语义 | 变不变 |
|---|---|---|---|
| `GET /` `GET /health` | 浏览器 / 脚本 | 单页 / 状态 | 不变 |
| `/harness` | `WebReviewer` | 跳 A，一次 run 一条 | **不变**（仍只有一个，第二个 1008 拒） |
| `/feed` | `LiveFeedTrace` | 实时 trace 单向转播 | 不变（agent 取帧的源） |
| `/ui` | 浏览器 | 跳 B + **新增 `proposal` 推送** + **新增 `discuss` 收** | 加两类消息 |
| （agent 进程自身端口，如 `ws://127.0.0.1:8770`） | 后端（WS 客户端） | **跳 C**：`seed`/`turn`/`close` → agent；`proposal` → 后端 | 新增端点，**在 agent 进程**，后端经 `.env` 的 `AGENT_REVIEWER_URL` 找地址 |

角色：harness / 后端 / 前端三者的职责与 web_reviewer spec 一致；**新增第四角色 `AgentReviewer`**，
是**独立进程**（`python -m pokemon_agent.agent_reviewer`，地址在 `.env` 的 `AGENT_REVIEWER_URL`），经**跳 C WS**
与后端通信，与前端、harness 均无直接 WS。

## 三、信封

### 3.1 跳 B 改动（放 `schemas/review_backend/communication/`）

| 信封 | 字段改动 |
|---|---|
| `FromReviewBackendToFrontendAskReq` | `deadline: float` → **`float \| None`**（人模式 `None` = 无倒计时） |
| `FromReviewBackendToFrontendSettleReq` | `by: Literal["human","timeout","harness_gone"]` → **加 `"agent"`** |
| `FromFrontendToReviewBackendAnswerReq` | **加** `by: Literal["human","agent"] = "human"`（前端标记自动提交来源） |

`by` 在 `settle` 的判定（§4.5）：内容非空且 `answer.by=="agent"` → `agent`；`=="human"` → `human`；
内容为空（插话空串 / 审无 verdict）→ `timeout`（无论 `by`，空框 = 当没人答）。

### 3.2 新增信封（同目录）

| 信封 | 方向 | 字段 |
|---|---|---|
| `FromReviewBackendToFrontendProposalReq` | 后端 → 网页 | `msg="proposal"` `seq` `proposal: ProposedAnswer` `round: int` |
| `FromFrontendToReviewBackendDiscussReq` | 网页 → 后端 | `msg="discuss"` `seq` `text: str` |
| `ProposedAnswer` | — | `text: str \| None = None` `verdict: AuditVerdict \| None = None` `note: str = ""`（与 `AnswerReq` 同形，与 agent 内部 `ProposedAnswer` 同名同源，建议直接复用同一模型） |

- `proposal` 无 Resp：后端推了就完，前端回显即可；首轮 `round=0`，每次「发给 AI」`round+1`。
- `discuss` 无 Resp：后端调 `agent.turn` 后自然推下一笔 `proposal`；前端不需要 ack（先答先得：
  同一 `seq` 若已在处理，忽略后续 `discuss`，避免并发覆盖）。
- `seq` 由后端分配（沿用现有 `self._seq`），`proposal` / `discuss` 都带它对齐到当前 pending。

### 3.3 不改

- **跳 A 全不动**（`FromHarnessToReviewBackend*Req/Resp` 不变；`timeout_s` 字段保留但**后端不再用于自管超时**，见 §4.2）。
- **harness 六个落点、`Reviewer` 协议、`WebReviewer` 公开接口**全不动——它只多接受一个 `timeout=None`。
- `AuditVerdict` 已在 `schemas/harness/domain/audit_verdict.py`，跨跳共用，不搬。
- `AskReq` / `ProposedAnswer` / `ChatTurn` 跨跳复用：跳 B 的 `AskReq` 直接作为跳 C `seed` 的 `ask` 字段；
  `ProposedAnswer` 在跳 B `proposal` 与跳 C `proposal` 共用同一模型；`ChatTurn` 是跳 C `turn` 的 delta 类型。

### 3.4 新增：跳 C 信封（后端 ↔ agent 进程，放 `schemas/agent_reviewer/communication/`）

agent 是**独立进程**，后端是 WS 客户端、agent 是 WS 服务端。四件信封，按 `msg` 分流（与跳 A/跳 B 同构）：

| 信封 | `msg` | 方向 | 字段 |
|---|---|---|---|
| `FromBackendToAgentReviewerSeedReq` | `"seed"` | 后端 → agent | `seq: int` `ask: FromReviewBackendToFrontendAskReq` `frame: str \| None` |
| `FromBackendToAgentReviewerTurnReq` | `"turn"` | 后端 → agent | `seq: int` `delta: ChatTurn` `frame: str \| None` |
| `FromBackendToAgentReviewerCloseReq` | `"close"` | 后端 → agent | `seq: int` |
| `FromAgentReviewerToBackendProposalMsg` | `"proposal"` | agent → 后端 | `seq: int` `proposal: ProposedAnswer` `round: int` |

- `seed` = 原 `propose_first` 的全量发（`ask` + 帧）；`turn` = 增量（人改稿 delta + 帧）；`close` = 结算释放。
- `proposal` 无 Resp：agent 推了就完，后端转成跳 B `ProposalReq` 广播给 `/ui`；`round` 0 为首轮，每次 `turn` 后 +1。
- `seq` 由后端分配（沿用 `self._seq`），跳 C 与跳 B 同号对齐到当前 pending。
- 信封均以 `model_dump_json()` 走 WS 文本帧；`AskReq` / `ProposedAnswer` / `ChatTurn` 直接复用既有模型，不新造。

## 四、后端改动（`pokemon_agent/review_backend/backend.py`）

### 4.1 状态与构造

- `ReviewBackend.__init__` 加一个参数 `agent_client: AgentClient | None = None`（**WS 客户端封装**，
  不是 `AgentReviewer` 实例——agent 在另一进程）；存 `self._agent`。
- 保留 `_seq` / `_pending` / `_history` / `_feed` / `_ui` / `_harness`；`_feed` 现额外被 `_latest_frame()` 读取。
- 新增 `AgentClient`（放 `review_backend/agent_client.py`）：封装到 agent 进程的 WS 连接，提供
  `seed(seq, ask, frame)` / `turn(seq, delta, frame)` / `close(seq)` 三个发送方法，并在后台协程里
  监听 agent 推回的 `proposal`，转交后端广播。构造时**尝试连接** `.env` 的 `AGENT_REVIEWER_URL`；
  连不上**不抛、不崩**——记警告、置 `None`，降级为无 agent。

### 4.2 `_ask`：移除 self-timeout + 经跳 C 触发 agent

```python
async def _ask(self, conn, req):
    self._seq += 1
    has_agent = self._agent is not None            # AgentClient 连上了才有
    deadline = (time.time() + AI_COUNTDOWN) if has_agent else None   # AI 模式默认开倒计时
    ask = _to_ask(self._seq, req, deadline)
    answer = asyncio.get_running_loop().create_future()
    self._pending = _Pending(ask, answer)
    broadcast(self._ui, ask.model_dump_json())
    if has_agent:                                    # 经跳 C 把 seed 发给 agent 进程（不阻塞）
        frame = self._latest_frame()
        self._agent.seed(self._seq, ask, frame)       # 异步发送；agent 推回 proposal 后由监听协程广播
    gone = asyncio.ensure_future(conn.wait_closed())
    try:
        done, _ = await asyncio.wait({answer, gone}, timeout=None)    # ★ 移除 req.timeout_s
    finally:
        gone.cancel(); self._pending = None
    if answer in done:        by = answer_by(answer.result())        # human / agent / timeout
    elif gone in done:        by = "harness_gone"
    else:                    by = "timeout"                        # 理论不可达（timeout=None）
    if self._agent is not None:
        self._agent.close(ask.seq)                                   # 跳 C 发 close，释放 agent 侧该 seq
    settle = _settle(ask, answer.result() if answer in done else None, by)
    ...
```

要点：
- **`timeout=None`**：后端不再自管超时；人模式无限等（靠 harness_gone 或人答），AI 模式靠前端倒计时。
- **agent 不在进程内**：后端只调 `self._agent.seed(...)` 经跳 C 发消息，agent 推回的 `proposal`
  由 `AgentClient` 的后台监听协程收到后 `broadcast(self._ui, ProposalReq(...))`——后端主循环不阻塞等 agent。
  agent 抛错 / 连接断 / 返回空 → **不推 proposal**（前端照常等人或倒计时），不污染 settle。
- `frame` 来自 `_latest_frame()`（见 4.3）。

### 4.3 `_latest_frame`：从 `_feed` 取最新帧

```python
def _latest_frame(self) -> str | None:
    for raw in reversed(self._feed):
        try:
            ev = json.loads(raw)["event"]; c = ev.get("content") or {}
        except (ValueError, KeyError, TypeError):
            continue
        if c.get("frame"):
            return c["frame"]          # 完整 data URI（data:image/png;base64,…）
    return None
```

只取 `content.frame` 一个字段——后端仍不认识游戏语义，符合 spec §6.4"后端不懂游戏"。

### 4.4 `discuss` 处理（`_serve_ui` 的 `async for raw` 里加分支）

```python
if m.msg == "discuss":
    self._discuss(raw); continue
```
`_discuss(raw)`：校验 `seq == self._pending.ask.seq` 且内容非空 → 取 `frame` →
`self._agent.turn(seq, ChatTurn(role="human", text=...), frame)`（经跳 C 发给 agent 进程）→
agent 推回新 `proposal(round+1)`，由监听协程广播。同一 `seq` 正在处理时忽略后续 `discuss`（先答先得）。
`agent is None` 时丢弃并打一行日志。

### 4.5 `settle` 的 `by` 判定

```python
def answer_by(ans: FromFrontendToReviewBackendAnswerReq | None) -> str:
    if ans is None:            return "timeout"
    filled = (ans.text not in (None, "")) or (ans.verdict is not None)
    if not filled:             return "timeout"        # 空框自动发 = 当没人答
    return ans.by                                      # "human" / "agent"
```

`_settle` 其余不变（插话取 `text`，审取 `verdict`+`note`），只是 `by` 来源从 `answer_by` 来。

### 4.6 `_to_ask`：deadline 入参

`_to_ask(seq, req, deadline)` 把 `deadline` 直接写入 `AskReq.deadline`（人模式 `None`）。

## 五、AgentReviewer 模块（`pokemon_agent/agent_reviewer/`）

### 5.1 目录（独立进程）

```
pokemon_agent/agent_reviewer/
    __init__.py        AgentReviewer 出口
    provider.py        复制并简化的 DeepSeekProvider（见 5.2）
    agent.py           AgentReviewer：seed / turn / close + 状态（进程内持有 _convs）
    schema.py          ProposedAnswer / ChatTurn（内部，不进 schemas 包）
    server.py          WS 服务端：收跳 C 的 seed/turn/close，调 AgentReviewer，推 proposal
    __main__.py        `python -m pokemon_agent.agent_reviewer`：读 .env 的 `AGENT_REVIEWER_URL` 解析 host/port 起 WS server（CLI `--host`/`--port` 可覆盖）
```

**不 import `brain` 任何东西**（边界：复制而非依赖，"谁消费谁持有 provider"的先例见
`memory/Local*Provider` 从 brain 搬出）。**不 import 后端进程的任何东西**——它是独立进程，
只经跳 C WS 与后端通信。后端侧对应的客户端封装（`AgentClient`）放 `review_backend/` 下。

### 5.2 `provider.py`：复制 `DeepSeekProvider` 并去 brain 依赖

- 从 `pokemon_agent/brain/providers.py` 复制：`IMAGE_TOKEN_FLOOR` / `_POST_POOL` /
  `_OpenAICompatibleBase` / `_png_bytes` / `_dump` / `_DUMP_DIR` / `_MultimodalMixin` /
  `DeepSeekProvider`（**只留 DeepSeek，删 Qwen/Ark/`pack_images_grid`/`provider_for`**）。
- **去 brain schema 依赖**：`complete` / `describe` 改为收裸字段——
  `describe(prompt: str, images: list[str]) -> DescribeResult`（`DescribeResult{text, input_tokens, output_tokens, cached_tokens, reasoning_tokens}`），
  不再收 `VisionDescribeReq` / 不再返 `VisionDescribeResp`。理由：agent 是叶子，直接吃
  字符串最干净，不引入对 brain 数据模型的耦合。
- 构造定值：`model="deepseek-flash"`、`temperature=0`（复核要确定性）、`timeout=20`
  （视觉调用预算，见 brain providers docstring 的 20/45 分档）、`thinking=False`、`multimodal=True`。
- `json_mode=False`（复核输出用 prompt 约束 + 本地解析，避开"空 content"风险；见 providers docstring）。

### 5.3 `agent.py`：`AgentReviewer`（进程内持有对话状态）

```python
class AgentReviewer:
    def __init__(self, model: str = "deepseek-flash") -> None:
        self._llm = build_deepseek(model, temperature=0, timeout=20)   # 5.2 的 provider
        self._convs: dict[str, list[ChatTurn]] = {}

    def seed(self, ask: FromReviewBackendToFrontendAskReq,
             frame: str | None) -> ProposedAnswer:
        conv = [ChatTurn(role="system", text=_SYSTEM)]
        conv.append(ChatTurn(role="user", text=_seed_user(ask, frame is not None)))
        if frame: self._convs[str(ask.seq)] = conv
        else:     self._convs[str(ask.seq)] = [ChatTurn(role="system", text=_SYSTEM)]
        return self._call(str(ask.seq), frame)

    def turn(self, seq: str, delta: ChatTurn, frame: str | None) -> ProposedAnswer:
        self._convs[seq].append(delta)           # 增量：只追加，不回灌整段
        return self._call(seq, frame)

    def close(self, seq: str) -> None:
        self._convs.pop(str(seq), None)

    def _call(self, seq, frame) -> ProposedAnswer:
        conv = self._convs[seq]
        prompt = _render(conv)                    # system + 逐轮 user/assistant 拼成一段 text
        images = [frame] if frame else []
        try:
            res = self._llm.describe(prompt, images) if images else self._llm.complete(prompt)
        except (EmptyCompletion, ImageNotDelivered, ProviderRejected, ToolTimeout):
            return ProposedAnswer()               # 失败 = 空提案（后端不推）
        return _parse(res.text, ask_kind=conv)    # 见 5.4
```

状态生命周期：`self._convs` 按 `seq` 持有对话；`seed` 建、`close` 删；
**与 agent 进程同生同死，agent 重启即失**——即使 agent 崩了，run 不受影响（后端视其缺失为"没人答、认账"，见 §9）。
`server.py` 收到跳 C `seed`/`turn`/`close` 时分别调用这三个方法，并把 `_call` 的返回值包成
`ProposalMsg` 经同一 WS 推回后端。

### 5.4 prompt 与解析

`_SYSTEM`（复核席角色，三条硬判据）：

> 你是「人和 AI 复核席」里的 AI 复核者。harness 会推来一份**已给出的结论**与它的证据/画面。
> 你的任务只表态：**这份结论与证据/画面一不一致**。
> - 审（verdict）：结论说"目标已达成 / 任务通过"时，你要么**认账**（同意），要么**推翻**（不同意），
>   推翻**必须**给一句理由；你不替 harness 决定下一步。
> - 插话（inject）：只输出一句改进意见，或"无意见"。
> 只输出结论本身，不要解释你的思考过程。

`_seed_user(ask, has_frame)`：把 `ask.body` + `ask.events`（若审）+ `ask.kind` + `ask.form_kind`
拼成给模型的指令文本；帧由 `describe` 的 `images` 单独传（不进文本）。

`_parse(text, ask_kind)`：
- `audit`：`text` 含「推翻 / 不同意 / 不通过 / 没达成」→ `verdict=OVERTURN` + 取「理由：…」后文作 `note`；
  含「认账 / 同意 / 通过 / 达成」→ `verdict=ACCEPT`；取不到明确词 → 默认 `ACCEPT`（保守，误判"没成"代价小）。
- `inject`：`text` 原样作 `ProposedAnswer.text`（v1 实际恒空，见 card §六判据 3，但保留解析）。

> 注：v1 不引 `json_mode`，靠关键词解析；真机跑若发现模型爱加客套话，再加 `json_mode` 或收紧 prompt。

## 六、前端改动（`pokemon_agent/review_backend/page.py`）

在现有「待答」卡片内叠加，不动实时 / 历史区结构：

1. **模式开关**：卡片顶部加两个按钮「AI 接管 / 我来处理」。`ask.deadline` 非 `None` → 默认 AI 模式高亮；`None` → 默认人模式高亮。随时点切，影响**当前 pending + 未来**（切换即时生效，不重发 ask）。
2. **结论框**：卡片内加一个**始终可见、可编辑**的 `textarea#conclusion`。`proposal` 推送到达时填入（round 0 首填，round>0 更新为 AI 最新结论）；人可改。
3. **聊天栏**（可选但建议）：在结论框上方放一个只读的轮次区，把每笔 `proposal`（`round` + 文本）与每笔 `discuss`（人话）以时间线列出，让"讨论"可见。最小实现可只显示最新 proposal + 结论框。
4. **倒计时仅 AI 模式**：`show()` 里若 `m.deadline != null` 且当前为 AI 模式 → 启动 30s 倒计时；**倒计时从首个 `proposal`（round 0）到达时开始**（避免 agent 还在想就被自动提交）；归零时若结论框非空 → `answer({..., by:"agent"})`，空 → `answer({by:"timeout"})`。若 agent 始终未响应（无 proposal），倒计时不触发自动提交（退化为人决定）。
5. **「发给 AI」按钮**：结论框旁边加「发给 AI」，点 → `ws.send({msg:"discuss", seq, text: 结论框内容})`；后端推回新 `proposal` 时刷新结论框与聊天栏。
6. **提交**：AI 模式下倒计时自动提交；人模式下人点「提交」→ `answer({..., by:"human"})`（结论框空则 `by` 仍 human、内容空，后端判 `timeout`）。
7. **settle 标签**：`settle()` 的 `by` 映射加 `agent: "AI 答了"`。

> 前端**不认识** agent 的存在——它只多收到一种 `proposal` 消息、多两个按钮、多一个倒计时分支。
> 「开关切 AI/人」是纯前端态，后端只在 `discuss` 时被动响应。

## 七、harness 侧（`pokemon_agent/harness/web_reviewer.py`）

- `WebReviewer.__init__(timeout: float | None = WEB_REVIEW_TIMEOUT)`：**允许 `None`**（去掉 `assert timeout > 0`）。
- `_exchange`：`self._conn.recv(timeout=self._timeout + GRACE_S)` 改为 `recv(self._timeout)`（`None` 即阻塞，不叠加 GRACE——后端不再自管超时，GRACE 无意义）。
- `inject` / `audit` 组跳 A 信封仍带 `timeout_s=self._timeout`（`None` 也照传；后端忽略，见 §4.2）。
- **六个落点、`Reviewer` 协议、`reviewing.py`、`ReviewMark` 全不动**：`answered = by in ("human","agent")`，评测三方分得清。

`check_harness.py` 装配：`--review` 时 `WebReviewer(timeout=None)`（agent 接管计时）；
若用户要纯人路径（后端 `--no-agent`），则 `WebReviewer(timeout=WEB_REVIEW_TIMEOUT)`，后端在 `--no-agent` 下
对每问仍按 `timeout_s` 自管超时（即保留原 30s 行为）。

## 八、配置与启动（.env + 三进程）

- **`.env` 的 `AGENT_REVIEWER_URL`**（新增）：后端找 agent 进程的唯一真相，`ws://127.0.0.1:8770` 为例。
- **后端 bind 仍是自己的 CLI**（`--host`/`--port`，不变）——只 agent 地址经环境变量，后端不碰自己 bind 的配置。
- 读取与降级：
  - 后端 `__main__.py`：启动时读 `.env` → `AGENT_REVIEWER_URL`；尝试连 `AgentClient`，
    **连不上不崩**——记 `[agent] 未连上，降级为无 agent` 并继续（前端退化为无提案 / 纯人）。
    `.env` / `AGENT_REVIEWER_URL` 缺失或空 → 同样视为无 agent（不强制）。
  - agent 进程 `__main__.py`：读同一 `.env` 的 `AGENT_REVIEWER_URL` 解析 host/port（或 CLI `--host/--port` 覆盖）
    起 WS server，绑定到该地址；与后端约定好同一端口（默认 `8770`）。
- `review_backend/__main__.py`：构造 `AgentClient(url)`（读 .env 的 `AGENT_REVIEWER_URL`）；`ReviewBackend(agent_client=...)`.
- agent 进程：**`DEEPSEEK_API_KEY` 缺失即 `RuntimeError` 当场停**（提示先配 key）；`AgentReviewer` 装配。
- 依赖：**标准库 `urllib`**（deepseek-flash 视觉版 HTTP，与 brain providers 同款）+ `websockets`（跳 C）。无新增第三方。
- 你本机起（三进程，AI 不经沙箱起长跑，二号铁律）：
  1. `python -m pokemon_agent.agent_reviewer`（起 agent 进程，读 .env 绑地址）
  2. `python -m pokemon_agent.review_backend`（起后端，读 .env 连 agent）
  3. 开网页；`check_harness.py --review`（WebReviewer 仍走 `/harness`，不变）

## 九、失败与降级（沿用 web_reviewer §5.3 精神）

| 情形 | 行为 |
|---|---|
| agent 调用失败 / 空提案 | 后端不推 `proposal`；前端 AI 模式无倒计时自动提交（退化为人决定）；人模式照旧；run 不受损 |
| **后端起时 agent 连不上**（.env 缺失 / `AGENT_REVIEWER_URL` 错 / agent 没起） | **不崩**：记警告、以无 agent 运行（前端退化为无提案 / 纯人），run 照跑 |
| **run 中途 agent 进程断了** | 后端 `AgentClient` 收连接断 → 该 seq 之后不推 proposal；本问与之后每问按"无 agent"处理（`by=timeout`）；run 不受损；不重连（agent 重启后只服务新 seq） |
| run 中途后端断了 | 同 web_reviewer：本问与之后每问按默认值、`answered=False`（`by=timeout`），每问一行 `[review]` 日志；不重连 |
| 双标签页 | 先答先得，后答 `answer_ack.ok=false`；`discuss` 同理（正在处理忽略后续） |

## 十、验收（机械可验）

1. 带 agent 起后端 + `check_harness --review`：网页在动，盘上账与不带 agent 时逐条同序；
   每个 pending 首笔 `proposal` 到达后聊天栏出现 AI 结论；AI 模式 30s 自动提交且 `by=agent`；
   人模式无倒计时、人提交 `by=human`；空框自动发记 `by=timeout`。
2. 「发给 AI」：点一次 → 后端 `agent.turn` 被调、新 `proposal` 推回、结论框更新、`close` 在 settle 后清掉该 `seq`。
3. 后端不在（未起）：run 照跑完，只打一行 `[feed]` / 降级日志，`answered=False`。
4. `ruff` + 定向测试绿（见 §11）：`AgentReviewer` 单测用 fake provider；`ReviewBackend` 测用 fake WS。

## 十一、实施顺序

| 步 | 内容 | 依赖 |
|---|---|---|
| A1 | 信封：跳 B 改（`AskReq.deadline`→`float\|None`、`SettleReq.by`加`"agent"`、`AnswerReq`加可选`by`）+ 新增 `ProposalReq`/`DiscussReq`/`ProposedAnswer`（跳 B）；新增**跳 C** 信封 `SeedReq`/`TurnReq`/`CloseReq`/`ProposalMsg` 及 `schemas/agent_reviewer/communication/` | — |
| A2 | `agent_reviewer/`：`provider.py`（复制 DeepSeek 去 brain 依赖）+ `schema.py` + `agent.py`（`seed/turn/close` + prompt + 解析）+ `server.py`（WS 服务端收跳 C、推 proposal）+ `__main__.py`（读 .env 起 server） | A1 |
| A3 | 后端：新增 `AgentClient`（WS 客户端，连 `.env` 的 `AGENT_REVIEWER_URL`、连不上降级）+ `ReviewBackend` 加 `agent_client` 参；`_ask` 去 self-timeout + 经跳 C `seed` + 监听协程收 `proposal` 广播 + `_latest_frame` + `discuss` 分支（跳 C `turn`）+ `settle.by` 判定 | A1 A2 |
| A4 | 前端：`page.py` 加开关 / 结论框 / 聊天栏 / 倒计时分支 / 发给 AI / settle 标签 | A1 |
| A5 | harness：`WebReviewer` 放开 `timeout=None`；`check_harness.py` 装配 `--review` 用 `None`；后端 `__main__.py` 读 .env 构造 `AgentClient` | A3 A4 |
| A6 | 测试：provider/agent 单测（fake）、后端集成（fake WS agent）、前端手测；`ruff` | A2 A3 A4 |
| A7 | 你本机三进程真机跑一次（起 agent → 起后端 → `check_harness --review`，网页切 AI/人、看画面、发 discuss） | A6 |
| A8 | CHANGELOG 一条（340）+ AGENTS/docs 同步（AGENTS §十二 已补 schemas 段 + §四 目录树，你已批） | A6（文档侧已完成，A7 仅真机验证） |

## 十二、风险 / 取舍

| 项 | 说明 |
|---|---|
| AI 模式下 agent 慢（≤20s）与倒计时赛跑 | 倒计时从首个 proposal 到达才开始，避开"agent 还在想就被自动提交"；agent 始终不响应则退化为人决定 |
| 前端倒计时是信任边界 | 后端不强制，人可改框后手动提交覆盖；恶意/卡死的前端只影响这一问，run 有 watchdog 兜底 |
| 后端内存状态 | `agent._convs` 随 `_feed`/`history` 同属后端内存，重启即失——与"后端不落盘"一致（不做历史，见 intent） |
| 模型换人 | agent 用 deepseek-flash（你确认）；若以后想换 qwen 视觉，只改 `provider.py`，不动 harness/前端 |
| 双模型成本 | 每个 pending 一次视觉调用（seed）+ 每轮 discuss 一次；讨论轮次多则成本线性涨，可接受再限轮 |
| agent 是独立进程 | 多一个进程要起、要连；`.env` 缺失 / `AGENT_REVIEWER_URL` 错 → 降级为无 agent（不崩）；agent 崩不伤 run，但本 seq 之后无提案 |
| 不做 | 自治 agent（工具/自停/自决）、给 agent 游戏状态/记忆、OCR 极小字、历史回看、鉴权/TLS/多 run |
