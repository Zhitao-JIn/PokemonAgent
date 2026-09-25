# plan —— Web Reviewer（独立后端 + 网页 + 实时 trace）

> 流程位置：intent（spec-v0 头部口径）→ spec.md → **plan.md** → PR → production
> 依据：`docs/web_reviewer/spec.md` v1（09-25）｜ 起草：2026-09-25 ｜ 状态：**实施中**
> 分支：`web-reviewer`（checkpoint-v2 已于 09-25 并入 main）
>
> 进度：W1 + W2a ✅ 09-25 合并做（`answered` 必填，所有实现得一次改齐），CHANGELOG 248；
> W2b + W2c ✅ 09-25 合并做（推翻理由要能到下一次 plan），CHANGELOG 249；
> W3 ✅ 09-25，CHANGELOG 250（`review_backend/` 实际是 4 个文件：出口、`backend.py`、`page.py`、`__main__.py`）

---

## 〇、排序原则

1. **先契约后实现**：W1 只动信封与 domain 模型，行为零变化；后面每步在稳定的形状上加。
2. **先进程内、后跨进程**：W2 把落点规则、反馈回路、trace 字段在进程内做完，用 Null / Console / fake run 就能验；W3 起才碰网络。
3. **每步独立可验**：结束时 `pytest` 全过、fake run 的 `node_io` 全过、ruff 干净，不留跑不起来的中间态。
4. **每步 = 一条 CHANGELOG 编号条目**（从 248 起）；commit 等你说再做；CRLF 文件保持 CRLF。
5. **删旧放最后**：FileReviewer 等真机在网页上答通了再删（W6）。

## 一、步骤总览

| 步 | 内容 | 依赖 | 行为变化 |
|---|---|---|---|
| W1 | 信封与 domain：`InjectResp`、`AuditResp` 分文件、`AuditVerdict` 挪 domain、`answered`、`AuditReq.outcome` 扩成员、`JudgeFeedback`、跳 A / 跳 B / Feed 信封 | — | 无 |
| W2a | Reviewer 接口改签名：Protocol / Null / Console / `reviewing.py` / `TapeReviewer`；`ReviewMark` 加 `answered` `wait_s`、审填 `form_kind`；`review_render.py` 抽出 | W1 | 无（账上多字段） |
| W2b | 落点规则：episode judge 插话 → 审（删重问循环、删 `JudgeReq.human_note`）；run 补审裁决；`judge_verdict` 加 `audit` | W2a | **有**：人不能再让 judge 改口，只能翻转 |
| W2c | 裁决反馈回 plan：两层 state 加 `last_judge`，`DecomposeReq` / `PlanOnceReq` 加字段，两份 prompt 加一段 | W2b | **有**：拆解 / 规划 prompt 多一段 |
| W3 | 后端 `pokemon_agent/review_backend/`（`/` `/health` `/harness` `/ui`）+ 网页（问人部分）+ config 常量 + pyproject | W1 | — |
| W4 | `WebReviewer` + `check_harness.py --review` 改接 Web | W2a W3 | — |
| W4b | `LiveFeedTrace` + `/feed` + 网页时间线与画面 | W3 | — |
| W5 | 自测（脚本当源程序 / 当网页） | W4 W4b | — |
| ★ | **你本机**：①真机 `--review` 在网页上答一次 ②`check_checkpoint.py --record` 重录 | W5 | — |
| W6 | 删 FileReviewer 及残留；spec 文档同步 | ★ | — |
| W7 | AGENTS（需你批）+ 记账收尾 | W6 | — |

---

## W1 信封与 domain（行为零变化）

**新增 / 挪动**
- `schemas/harness/domain/audit_verdict.py`：`AuditVerdict` 从 `FromHarnessToReviewerAuditReq.py` 挪来。
- `schemas/harness/communication/FromHarnessToReviewerAuditResp.py`：从 AuditReq 文件拆出；加 `answered: bool`（必填）。
- `schemas/harness/communication/FromHarnessToReviewerInjectResp.py`：`text` `answered`。
- `FromHarnessToReviewerAuditReq.outcome`：`EpisodeOutput | TaskOutput | FromHarnessToBrainToolJudgeResp`。
- `schemas/harness/domain/judge_feedback.py`：`JudgeFeedback{done, why, audit: AuditVerdict | None, note}`。
- 跳 A（`schemas/harness/communication/`）：`FromHarnessToReviewBackend{Inject,Audit}{Req,Resp}`、`FromHarnessToReviewBackendFeedReq`。
- 跳 B（新包 `schemas/review_backend/communication/`）：`FromReviewBackendToFrontend{Ask,Settle,Feed}Req`、`FromFrontendToReviewBackendAnswer{Req,Resp}`。
- 出口同步：`schemas/harness/__init__.py`、`schemas/harness/domain/__init__.py`、新包 `__init__`。

**这一步不改调用方**：Protocol 仍返回 `str`（W2a 改），`answered` 先由现有实现填上，保证能跑。

**验收**：`pytest` 全过；`python -c "import pokemon_agent.schemas.review_backend"` 不拉起 harness（断言 `sys.modules` 里没有 `langgraph`）。

## W2a Reviewer 接口改签名

- `harness/interface/reviewer.py`：`inject(req) -> FromHarnessToReviewerInjectResp`；改 `audit` docstring（note 写进表行，不是拼提示词末尾）。
- `NullReviewer`：`answered=False`。`ConsoleReviewer`：人答了 `True`、超时 `False`；渲染改调 `review_render`。
- `harness/review_render.py`：`render_form` / `render_outcome` / `render_events`，从 `ConsoleReviewer` 抽出，W4 共用。
- `harness/reviewing.py`：`ask_inject` 对调用方仍返回 `str`（五处调用点不动）；计时得 `wait_s`；`ReviewMark` 记 `answered` `wait_s`；`ask_audit` 填 `form_kind`（`EpisodeOutput` / `TaskOutput` / `JudgeVerdict`）。
- `schemas/harness/domain/review_mark.py`：加 `answered: bool`、`wait_s: float`。
- `tools/replay/tape_reviewer.py`：磁带上重建两个 Resp（`answered` 从账上取）。
- 渲染（`tools/trace/render.py`）、`node_io` 契约、`docs/spec/DATAFLOW.md` 事件表同步。

**验收**：`node_io` 过；回放测试过（用新录的 fake 磁带）。

## W2b 落点规则

- `harness/episode/review_and_judge/__init__.py`：删 `while True` 重问循环；`verdict.done` 为真时 `ask_audit(outcome=verdict, …)`；OVERTURN → `termination` 回机械结论（不是 `GOAL_DONE`）；note 进 `record_verdict(human_note=…)`。
- `harness/run/review_and_judge/review_and_judge.py`：步骤 3 之后同款审裁决。
- 审裁决的 `events`：取本层 judge 那一笔 `judge_call`（它的 prompt 就是模型看的材料）。
- `FromHarnessToBrainToolJudgeReq`：删 `human_note`；`tools/prompts/judge_success.py` 删 `append_human_note` 那段；`calls/judge_success.md` 若有引用一并清。
- `harness/judging.py::record_verdict`：加 `audit: AuditVerdict | None`；渲染与 `node_io` 同步。

**验收**：fake run 三场景：①judge 判成 + 认账 → 收工（与现状同）②judge 判成 + 推翻 → 继续跑、`judge_verdict.audit=overturn`、`termination` 为机械结论 ③judge 判没成 → 不问人。需要一个"按脚本答"的假 reviewer（测试件，放 `tests/_fake_run.py`）。

## W2c 裁决反馈回 plan

- `EpisodeRunState` / `RunState`：`last_judge: JudgeFeedback | None = None`；`review_and_judge` 在"问过模型且本层继续跑"时写，否则保持 None / 旧值按 spec §4.6。
- `plan_episode` / `plan_run`：把 `state.last_judge` 放进 `DecomposeReq.last_judge` / `PlanOnceReq.last_judge`。
- `tools/prompts/decompose.py` / `run_plan.py` + 模板：`last_judge` 非空时加「上一次本层判定」一段。
- 存档清单：`RunState` 多一个有缺省的字段，旧清单能读（不做别的兼容）。

**验收**：fake run 场景 ②的下一次 decompose prompt 里出现「人推翻了这个判定：…」；场景 ③出现模型的 `why`；首轮（None）decompose 不出现这一段（模板多了一条规则，prompt 不再与改前逐字相同）。

## W3 后端 + 网页（问人部分）

- `pokemon_agent/review_backend/__init__.py`：`ReviewBackend`（seq / pending Future / history deque / feed deque）、`/harness` `/ui` handler、`process_request` 回 `GET /` `GET /health`；单 `/harness` 连接约束（第二条 1008）。
- `review_backend/page.py`：单页 HTML/CSS/JS——待答卡片（插话 / 审两副面孔）、历史、连接状态、自动重连。
- `review_backend/__main__.py`：`python -m pokemon_agent.review_backend [--port]`，端口被占即报错退出。
- `config.py`：`WEB_REVIEW_TIMEOUT = 30.0`（docstring 写清两个消费者）。端口 8765 是部署配置、不进 config：后端 `--port`，缺省值住 `review_backend/__main__.py`。
- `pyproject.toml`：主依赖加 `websockets>=16`；删 `api` 组与 dev 的 `httpx`。**`uv.lock` 需你本机 `uv sync` 重锁。**

**验收**：后端单测（asyncio 内起服务、`websockets` 客户端当两端）：正常答、超时回默认、双 `/harness` 被拒、`/ui` 重连补发、先答先得。

## W4 WebReviewer

- `harness/web_reviewer.py`：构造连 `/harness`（失败 `OSError`）；`inject` / `audit` = `review_render` → 跳 A → `recv(timeout+5)` → 进程内 Resp；断连后降级（`answered=False` + 每问一行 `[review]` 日志）。
- `experiment/real_check/check_harness.py`：`--review` 改接 `WebReviewer(run_id, url)`；看门狗依据改为 30s×问数；打印起跑三步提示。

**验收**：W5 一并测。

## W4b 实时 trace

- `tools/trace/live_feed.py`：`LiveFeedTrace(inner: TracePort, url)`——`append` 先落盘再入有界队列；daemon 线程连 `/feed` 发；满丢最旧、断了丢弃并只打一行日志。
- 接线：`TraceTool.local(..., live_feed_url=None)` 包在 `LocalTrace` 外；`build_real(..., live_feed_url=…)` 透传；`check_harness.py --review` 传后端地址。
- 回放段不推：磁带未切换时 `TapeTrace` 不落新账——核对这一点成立即可，不成立就在 `LiveFeedTrace` 上加 `paused`。
- 后端 `/feed` handler + `FeedReq` 转播；网页加「当前画面」与时间线，审时挑被审对象的首末帧。

**验收**：后端不在时 fake run 耗时与不接 feed 相差无几、账逐字相同；后端在时 `/ui` 收到的事件数 = 落盘数（未丢的情况下）。

## W5 自测

脚本当源程序（fake run + `WebReviewer`）、脚本当网页（`/ui` 客户端按预设答）：插话有话 / 没话、四个审点认 / 推、超时、后端中途被杀（降级且 run 跑完）、网页重连补发、feed 画面到达。

## ★ 你本机

1. `python -m pokemon_agent.review_backend` → 浏览器开页 → `check_harness.py --review`，在网页上至少答一次插话、推翻一次审；看 `wait_s` 判断 30s 够不够。
2. `check_checkpoint.py --record` 重录，五项全过。

## W6 删旧

- 删 `harness/file_reviewer.py`、`harness/__init__.py` 相关导出与 docstring、`check_harness.py` 残余；`.workbuddy/` 两个残留文件与 `_to_delete/_filereviewer_retired/`（**删前问你**）。
- `docs/spec/harness/SPEC.md` §六重写；`docs/spec/experiment/SPEC.md` FileReviewer 处；DATAFLOW。

## W7 收尾

- AGENTS §十二：`schemas/frontend` 那段补「`schemas/review_backend/` 为跳 B 信封」（**需你批文字**）；目录树加 `review_backend/`。
- ROADMAP 对应条目状态。

---

## 二、测试放哪（按规矩先问）

| 测什么 | 放哪 | 为什么要 |
|---|---|---|
| 落点规则三场景 + 反馈回 plan | `tests/test_review_points.py`（fake run + 脚本化假 reviewer） | 行为变化点，是 W2b/W2c 的用法示范 |
| 后端协议 | `tests/test_review_backend.py` | 跨进程协议最容易悄悄坏 |
| feed 不拖累 run | 并进上一个文件 | 一条断言 |

W5 的端到端脚本放 `experiment/real_check/check_web_reviewer.py`（与其它核对脚本同处，gitignored）。

## 三、待定

| # | 问题 | 建议 |
|---|---|---|
| 1 | 从哪切分支：`checkpoint-v2` 先并 main 再切，还是直接在 `checkpoint-v2` 上切 | **先把 checkpoint-v2 并入 main**，再从 main 切 `web-reviewer`——两块互不相关，分开合更好回滚 |
| 2 | 测试放法（§二） | 按表 |
| 3 | ConsoleReviewer 留不留 | 留（零依赖，调试不用起后端） |
