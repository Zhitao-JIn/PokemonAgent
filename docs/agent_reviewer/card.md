> 状态：旧实现已在 reviewer R6c（529）删除；当前入口为 `python -m pokemon_agent.reviewer --seats human`。新 AI 席待 R7。以下正文作为历史设计保留。

# card —— Agent Reviewer：人 + AI 在同一个聊天栏里磨出一个结论，再发给后端

> 流程位置：**card.md**（本文件：它是谁 / 契约是什么 / 边界在哪）→ spec → plan → 落码
> 状态：**已实施 v3.4**（2026-09-29 用户纠正：agent 是**独立进程**、地址写进 `.env` 的
> `AGENT_REVIEWER_URL`（非 config.json）、走**跳 C（WS）**而非进程内调用；Fork B 确认无真 agent、
> deadline 前端控制、异步带回结论、超时自动发、结论框回灌 agent）。代码已落（A1–A6，CHANGELOG 340），
> A7 三进程真机跑交用户本机。
> 关联：`docs/web_reviewer/spec.md`（设施设计，已落地 W1–W5）、`docs/web_reviewer/intent.md`
> （纯展示前端，与本文**正交**）、`pokemon_agent/harness/interface/reviewer.py`、
> `pokemon_agent/review_backend/backend.py`、`schemas/review_backend/communication/`、
> `pokemon_agent/brain/providers.py`（`DeepSeekProvider`，视觉版直接复用其路由）

---

## 一、一句话

协作审席：人 + AI 在同一个**聊天栏**里磨出一个最终结论，再发给后端。
AI 是后端里的一个**一次性多模态 LLM 提案器**（**deepseek-flash V4.1，原生视觉**，看画面），
人是聊天栏里的拍板者；前端一个开关随时切「谁拍板」。**harness 一字不改**——它只发 `ask`、
收 `answer`，不知道背后是人、是 AI、还是人跟 AI 聊出来的。

```
harness(WebReviewer) ──WS /harness──► 后端 ──┬─ 跳C WS ─► agent_reviewer 进程（deepseek-flash 视觉版，独立进程）
                                            ├─ 把 ask + AI 提案 广播 ──WS /ui──► 浏览器（聊天栏）
                                            └─ 收最终 answer ──► 翻成跳 A Resp ──► harness
（agent 地址在 `.env` 的 `AGENT_REVIEWER_URL`；后端起时连，连不上降级为无 agent）
```

## 二、拓扑：答案怎么回（四种角色）

| 角色 | 在哪 | 干什么 |
|---|---|---|
| **harness** | run 进程 | 发 `ask`（跳 A）→ 收 `answer`（跳 A）。**不变**，不知道有 AI |
| **后端 review_backend** | 常驻进程 | 唯一的协调者：收到 `ask` → 取最新帧 → **经跳 C WS 把 `ask+frame` 发给 agent 进程** →
  收到 agent 推回的提案 → 把 `ask + 提案` 广播给浏览器 → 按当前模式提交最终 `answer` → 打 `by` 标签 → 翻跳 A 回 harness |
| **agent_reviewer** | **独立进程**（`python -m pokemon_agent.agent_reviewer`，地址在 `.env` 的 `AGENT_REVIEWER_URL`） | **跳 C 的 WS 服务端**：收 `seed`/`turn`/`close`，持有按 `seq` 的对话状态、调 deepseek-flash 视觉版、把提案推回后端。
  **不连 /ui、不是 Reviewer 实现** |
| **前端（浏览器）** | 网页 | 聊天栏：显示 AI 提案/发言，人编辑/拍板，把最终 `answer` 发回后端。
  「人和 AI 讨论」在 v1 就是「人看 AI 提案 → 人决定/改写 → 点『发给 AI』回灌 → agent 再给结论」 |

## 三、身份卡

| 项 | 取值 |
|---|---|
| 名字 | `AgentReviewer`（暂定；v1 只是一次 LLM 调用，**不是真 agent**） |
| 占据的位置 | **独立进程里的多模态提案服务**（跳 C WS 服务端），不是 `Reviewer` 的第五个实现、不进 harness 进程、也不进后端进程 |
| 模型 | **`deepseek-flash`**（V4.1 Flash，2026-09-10 起原生多模态；旧 `deepseek-v4-flash-vision-exp` 已路由到它） |
| 形态（v1） | **有状态对话提案器**：agent 自身**按 `seq` 持有每段对话的 transcript**；每轮只收**增量 delta**
  （人的新发言/改写），不再整段回灌。仍**零工具、零自治循环、零游戏状态/记忆** |
| 它替代谁 | 人。不是 judge，不是 verify（分工见 §七） |
| 它看什么 | 一问带来的全部文本：`prompt` / `body` / `events`，**外加画面**（最新 `sense_frame` 的
  `data:image/png;base64,…`，后端从自身 `_feed` 取） |
| 它看不到 | 图状态、目标表、记忆库、动作空间；**不读 OCR 精度要求高的极小字**（帧 160×144 会被上采样到 ~384×384） |
| 它不能做 | 改状态、改计划、按键、回退时间；**推翻只是翻转结论**，后果全由 harness 盖章 |
| 延迟预算 | **纯 AI 态**：agent 自定 / 或 30s 硬上限（见 §四）；**交互态**：无 timeout |
| 失败后果 | **零**：提案缺失/报错 = 当没人答，run 继续（与超时同义） |

## 四、协作聊天与开关（核心新机制）

**一次 `ask` 的生命周期（deadline 前端控制，agent 异步带回结论）：**

1. 后端收到 `ask`（跳 A）→ 从自身 `_feed`（内存最近 300 条）取最新 `sense_frame` 的 data URI；
2. 后端**经跳 C WS 异步**把 `seed(ask, frame)` 发给 agent 进程；agent 一返回结论就**经跳 C 推回**，
   后端立刻转成 `proposal` 推给前端（新增 `proposal` 推送消息，见 §八）——不是把结论塞死在 `ask` 里，所以「agent 随时带回结论」；
3. 前端聊天栏渲染 AI 结论 + 一个**始终可见、可编辑的结论框**；按**当前模式**推进：

| 模式（前端开关，随时切） | 谁拍板 | 提交动作 | `settle.by` |
|---|---|---|---|
| **AI 模式**（没人） | 前端自动 | agent 结论一回来即填入结论框；**前端倒计时**（默认 30s，**前端控制**）归零即自动提交当前框内容 | 框内容非空 → `agent`；agent 一直没回、框空 → `timeout` |
| **人模式**（有人） | 人 | 结论框可**接受 / 改写 / 自己写**，点「发送」才提交；**无 countdown**，人决定何时回 | `human` |
| 人模式但人没发 | — | 连接断开/页面关才作废 | `harness_gone` |

**结论框是共享工件，始终可见可改、且回灌 agent**：人在结论框里改写后点「发给 AI」→ 后端**只发这一轮的增量**
（人改稿 delta + 当前帧）给 agent；agent 在自己持有的该 `seq` 对话里追加、调模型、出新结论、再次推送。
后端不再累积/回灌整段 transcript（帧在 seed 时已存，讨论期间游戏冻结、帧不变，不重发）。
如此往复即「人和 AI 讨论」。**最终「提交」**把结论框内容作为 `answer` 发回后端 → 翻跳 A 回 harness。

**超时 = 前端倒计时（只在 AI 模式）**：倒计时归零，前端**直接把当前结论框内容自动提交**
（by 见上表）——「超时直接发」发的就是此刻框里那版，不另等 agent。AI 模式下人想在倒计时内接管，
改框 + 点「发送」即可（此时按 `human` 算，覆盖自动提交）。

**「随时切换」语义**：开关影响**当前 pending + 未来**的每问。
- 人 → AI：本问还没被人发 → 取消等待，改走前端倒计时自动提交（受倒计时约束）；若 agent 结论已回则直接填框；
- AI → 人：本问还没被自动提交 → 取消倒计时，改交人拍板（人无 countdown）。

> **落地小对齐（已知，待 spec 定）**：deadline 改为**前端控制**，后端不再用 `asyncio.wait(timeout_s)`
> 自管超时；后端只在「收到前端 answer」或「harness_gone」时 settle。交互态（人模式）无倒计时，
> 故 `ask.deadline` 传 `None`，`WebReviewer.recv(None)` 无限等（直到连接断）——这是顶层「harness
> 不变」的唯一例外点，改动极小。AI 模式的 30s 现在住在前端倒计时里，后端不感知具体数值。

## 五、输入契约（agent 持有 transcript，后端只发增量；跨进程走跳 C WS）

**进程外、走 WS**：三方法不再是后端里的 Python 调用，而是**跳 C 信封的载荷**
（`schemas/agent_reviewer/communication/`）。后端是 WS 客户端、agent 是 WS 服务端。
**transcript 是 agent 进程的内部状态，按 `seq` 持有**——现在它天然住在 agent 进程里，不进后端内存。

| 跳 C 信封 | 方向 | 载荷（字段） |
|---|---|---|
| `FromBackendToAgentReviewerSeedReq` | 后端 → agent | `msg="seed"` `seq` `ask: FromReviewBackendToFrontendAskReq` `frame: str \| None` |
| `FromBackendToAgentReviewerTurnReq` | 后端 → agent | `msg="turn"` `seq` `delta: ChatTurn` `frame: str \| None` |
| `FromBackendToAgentReviewerCloseReq` | 后端 → agent | `msg="close"` `seq` |
| `FromAgentReviewerToBackendProposalMsg` | agent → 后端 | `msg="proposal"` `seq` `proposal: ProposedAnswer` `round: int` |

- `seed` 的载荷：`ask`（跳 B 信封，`prompt`/`body`/`events`/`kind`/`form_kind`…，`AskReq` 直接复用）+ `frame`
  （`_feed` 最新 `sense_frame` 的 data URI）——**这是唯一一次全量发**；
- `turn` 的载荷：**只 `delta`**（`{role:"human", text: 人改稿}`）+ 当前 `frame`（帧不变，顺手带上）；
- 状态生命周期：`agent._convs: dict[seq, list[ChatTurn]]`，`seed` 建、`close` 删；
  **与 agent 进程同生同死，agent 重启即失**（这是刻意：agent 不落盘；即使 agent 崩了，run 不受影响——
  后端视其缺失为"没人答、认账"，见 §八降级）；
- `kind` 决定产出：插话 → 提案 `text`；审 → 提案 `verdict` + `note`。

## 六、输出契约（提案 / 最终 answer / by）

**提案（进程内）**：`ProposedAnswer(text: str | None, verdict: AuditVerdict | None, note: str)`，
与跳 B `answer` 同形。三条硬判据写死在 prompt + 解析里：

1. **只表态，不给新结论**：推翻只是「这个结论不成立」，不替 harness 决定接下来做什么；
2. **推翻必给理由**（`note` 非空）：`note` 会进本层 `last_judge`，下一轮 `plan_*` 的 prompt
   出现「人推翻：<note>」——没理由的推翻会让规划瞎改；
3. **插话 v1 恒空**：提案的插话 `text` 一律空串（理由：插话会触发 `plan_*` 的 `while True`
   重问循环，不停插话 = 无限重问；要让它插话得先给循环加轮次上限，另一个改动）。

**最终 answer（跳 B，网页→后端）**：`FromFrontendToReviewBackendAnswerReq`
（`seq` / `text?` / `verdict?` / `note=""`）——**本信封不变**，前端默认 `by=human`。

**proposal 推送（后端→前端，新增，见 §八）**：`FromReviewBackendToFrontendProposalReq{seq, proposal, round}`。
agent 每产出一个结论就推一次（round 0 为首轮，后续轮递增）；前端据此刷新聊天栏与结论框。
`ask` 信封保留可选 `proposal` 字段（仅作 round 0 占位 / 向前兼容，可为空——因为 agent 是异步返回）。

**settle（后端→网页）**：`FromReviewBackendToFrontendSettleReq.by` 由
`Literal["human","timeout","harness_gone"]` **扩为** `Literal["human","agent","timeout","harness_gone"]`。
这是本方案**唯一的设施改动点**（见 §八）。

**评测口径（重要）**：harness 侧 `answered = by in ("human","agent")`。现在能分清三种：
人答 / AI 答 / 没人答——评测的「假阳率」标注不再被 agent 污染。
注意 AI 模式下「倒计时归零但框空（agent 没回）」按 `timeout` 结算（= 当没人答、认账），
**不会**污染成 `agent`——只有框里真有 agent 结论时才记 `agent`。

## 七、与现有机制的分工

| 机制 | 谁 | 判什么 | 落点 |
|---|---|---|---|
| `judge` | brain（模型） | 目标**达成了没有**（唯一位 `done`） | `review_and_judge` 格，落 `judge_verdict` |
| `verify` | brain（模型） | 行为/总结**是不是正样本**（标记器） | `*_done` 格，过滤进 summarize 的样本 |
| 人 / **Agent Reviewer** | 席上那位 | 对**一个已给的单一结论**认或推翻 | 同格，落 `review_audit`（`answered` / `wait_s` / `by`） |

**它是复核者（auditor），不是第二个 judge**：判「这份结论与它自己摆出的证据一不一致」
（`body` + `events` + 画面），不是「我重新判一遍目标成没成」——后者只是换个模型跑 judge，
与现有链路重复且无法对照。

## 八、边界澄清（回答「聊天放 agent 还是 harness」）

**聊天既不是 agent 的事，也不是 harness 的事——它是前端的 UX 形态。** 三层边界如下：

| 边界 | 左 | 右 | 接口 | 变不变 |
|---|---|---|---|---|
| harness ↔ 后端 | run 进程 | review_backend | `/harness` WS（跳 A 信封） | **不变**（交互态 `deadline=None` 是唯一点） |
| 后端 ↔ 前端 | review_backend | 浏览器 | `/ui` WS（跳 B 信封） | **新增 `proposal` 推送消息 + `settle.by` 增 `"agent"`；`ask.deadline` 改语义（None=人模式 / 数字=AI 倒计时）；倒计时改前端控制** |
| 后端 ↔ agent_reviewer | review_backend | **独立进程** | **跳 C WS（新增信封 `schemas/agent_reviewer/communication/`）** | 新增；agent 地址在 `.env` 的 `AGENT_REVIEWER_URL`（见 §九） |

要点：
- **harness 与 agent_reviewer 之间没有任何直接通道**。agent 是独立进程、坐在后端 `/ui` 这侧之外，
  harness 只经 `/harness` 找后端，两者只靠「ask→answer」这对信封经后端间接相遇 → 所以 harness
  的代码、六个落点、`Reviewer` 协议**全部不动**——这是「AI 顶替人」却「harness 零改动」的根本原因。
- **聊天栏是浏览器里的状态**：AI 结论由后端转发的 `proposal` 消息填入，人在结论框里编辑/拍板，
  最终 `answer` 从浏览器发回后端。所谓「人和 AI 讨论」在 v3.3 就是「人看结论 → 人改写 → 点『发给 AI』
  经跳 C `turn` 回灌 → agent 再给结论」的有状态多轮（非自治 agent）。
- **agent 持有按 `seq` 的对话状态**：transcript 是 agent 进程内部资产，后端只转发增量 delta；
  结算时 `close(seq)` 释放（与 agent 进程同生同死，重启即失）。
- **deadline 是前端资产**：后端不再持有/强制超时数值；30s 倒计时只活在 AI 模式的前端。
  后端只在「收到前端 answer」或「harness_gone」时 settle，不替前端掐表。
- **`.env` 的 `AGENT_REVIEWER_URL` 是 agent 地址的唯一真相**：后端起时读它连 agent；连不上≠崩——降级为无 agent（见 §九）。

## 九、provider 怎么放（deepseek-flash 视觉版）

- 新建 `pokemon_agent/agent_reviewer/provider.py`：**复制** `brain/providers.py` 的
  `DeepSeekProvider`（及 `LLMProvider` 协议），型号 `deepseek-flash`（V4.1，原生视觉）。
  要补一个多模态出口（复用 `complete` 的多模态分支或新增 `describe(images, prompt)`）：
- 请求格式（OpenAI 兼容 `/v1/chat/completions`，base_url 走项目既有 DeepSeek 网关）：

  ```json
  {
    "model": "deepseek-flash",
    "messages": [{
      "role": "user",
      "content": [
        {"type": "text",      "text": "<prompt+body+events+transcript 拼好的指令>"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,<frame>"}}
      ]
    }]
  }
  ```
- 复用项目既有的 `_png_data_uri` 产物（`data:image/png;base64,…`），无需自己拼。
- 约束（DeepSeek 视觉版）：48 MiB 包体上限；图片自动缩放（小帧上采样到 ~384×384）；
  每图最多计 1024 token；可选 `detail: low/high/original/auto`（粗看用 `low` 更便宜）。
- 这是**有先例的偏离**：`LocalEmbeddingProvider`/`LocalRerankerProvider` 当年从 brain 搬去
  `memory/`，「复制/搬出 provider」不算破 brain 边界（边界是「不许 import brain 实现」）。
  agentreviewer 因此完全不依赖 brain 包。
- 装配：provider + agent 都在 **agent 进程**内（`python -m pokemon_agent.agent_reviewer` 启动处实例化），
  不经 tool 层、不进后端进程（它是独立进程，见 §二/§八）。后端只持有到 agent 的 WS 客户端连接。

## 十、与 `docs/web_reviewer/intent.md`（纯展示）的关系

**正交，可并存**：

| | 纯展示前端 | Agent Reviewer |
|---|---|---|
| `/ui` 上 | 没人应答（只推 feed） | agent 提案 + 人聊 |
| harness 侧 | `--feed-url`，reviewer=Null | `--review` + `WebReviewer`（不变） |
| 共用 | 后端、`/feed` 实时流、`LiveFeedTrace` | 同左 |

先做哪个取决于你要「看得见」还是「有人（agent）替我拦一道」。两者都只动后端与前端，harness 不动。

## 十一、不做（v1 范围）

- 不改 `Reviewer` Protocol、不动六个落点、不动 Null / Console / Web / Tape 四实现；
- 不把 agentreviewer 接成 `Reviewer` 的第五个实现（它既不进 harness 进程、也不进后端进程，是独立进程）；
- v1 不做**自治 agent**（人不回 pushback 不给 AI 重想、AI 不自己决定何时停、不工具调用）；
  多轮是「agent 持有的对话状态 + 增量 delta」，不是 agentic loop；
- 不给它工具（查记忆/读盘/按键）、不做它自己的账（它答了什么已落在 `review_audit`，留完整
  prompt/响应是 v2）；不碰 `judge` / `verify`；不消费 OCR 精度要求高的极小字。

---

## 附录：机器可读 card（将来接 A2A / MCP 时的形状草稿）

```json
{
  "name": "agent-reviewer",
  "version": "0.1.0",
  "description": "独立进程内的多模态 LLM 复核席：经跳C WS 收后端 seed/turn，调 deepseek-flash 视觉版出提案推回；前端聊天栏让人拍板。",
  "role": "auditor-proposer",
  "stateless": false,
  "state": "per-seq conversation transcript (in agent process memory; cleared on settle via close(seq))",
  "transport": { "type": "ws", "role": "server", "address": "ws://127.0.0.1:8770 (from .env AGENT_REVIEWER_URL)", "caller": "review_backend (ws client)" },
  "model": "deepseek-flash",
  "consumes": ["ask (seed only)", "frame_data_uri (seed only)", "delta (per turn)"],
  "emits": ["proposed_answer"],
  "skills": [
    { "id": "audit_episode_output", "input": ["prompt","body","events","frame","transcript"], "output": ["verdict","note"] },
    { "id": "audit_task_output",    "input": ["prompt","body","events","frame","transcript"], "output": ["verdict","note"] },
    { "id": "audit_judge_verdict",  "input": ["prompt","body","events","frame","transcript"], "output": ["verdict","note"] },
    { "id": "inject",               "input": ["prompt","body"],                          "output": ["text"], "default": "''" }
  ],
  "constraints": {
    "no_state_mutation": true,
    "note_required_on_overturn": true,
    "inject_default": "empty",
    "sees_screen": true,
    "screen_format": "data:image/png;base64 (deepseek-flash multimodal)",
    "timeout": { "interactive": "none (human decides when to send)", "ai": "frontend countdown (default 30s, frontend-owned); auto-send on expiry; agent returns async via proposal push" }
  }
}
```
