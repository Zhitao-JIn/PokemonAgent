> R6c（529）清理说明：旧后端、控制台、网页与实时推送已删除；依赖旧后端信封的旧 AI 进程及其测试一并删除。R7 保留新 AI 席、依赖与探针工作。

# Reviewer plan —— 步骤、关卡、回退与合入

> 流程位置：intent.md → spec.md → **plan.md**（本文件）→ PR
> 依据：`docs/reviewer/spec.md`（§十六）；意图见 `docs/reviewer/intent.md`；协作规则见 `docs/workflow.md`
> 状态：R0 **已完成**（2026-10-18）：brain-scope 已合入主线（main d6e9aaa）；R1a = 514（提交 7eb5dba）、R2 = 515（提交 6a85edd）已验收；基线 `state_schema_hash()` = `5ea6dffeeb229b7c`（与 main 逐位相同）。R3 = 513（提交 b3e1985）已完成，随本次合入 main；R3b（516）已完成；用户授权新增 TaskState.last_judge，新哈希 `28e96b09966dc94e`，20 份评测存档已重打并真实恢复验收。
> 本文件中的 460 / 461 / 462 等旧编号以台账 `.coordination/ledger.md` 为准（R1a / R2 已重编号为 514 / 515）。
> R4（517）已完成于独立分支 `codex/reviewer-r4`，基于 R3b 提交 `b0035e8`；默认全量 1463 项、slow 3 项及 ruff 通过，两次破坏验证均拦截成功；状态哈希保持 `28e96b09966dc94e`。R3b 与 R4 均待合入。
> R5（518）已完成于 `codex/reviewer-r5`：前置报告 `3296bd5`，用户允许 recall 正常更新派生缓存；新增查询模型、窄读协议与 ViewReaders，默认全量 1515 项 / slow 3 项通过，状态哈希不变。
> R6a（519）已完成于 `codex/reviewer-r6a`：进程内 human 席、hub、命令与 PNG 展示；新增 52 项测试，默认全量 1567 项 / slow 3 项通过，693 文件 ruff 通过；状态哈希保持 `28e96b09966dc94e`。
> R6b（520）已完成于 `codex/reviewer-r6b`：单跳 WS、重连与幂等、独立入口、build 装配；新增 54 项测试，默认 1621 项 / slow 3 项通过，713 文件 ruff 通过；哈希不变。R6c（529）已删除旧栈，新 AI 席待 R7。
> v3（2026-10-17）：spec 已按 brain-scope v1.3 同步；新增 R0 与 §八；R3 / R5 / R6a 的内容与前置更新；编号与哈希关卡改为「恢复时重定」。
> v4（2026-10-17）：reviewer 改为独立进程（spec #23）：R5 缩为 reviewer 内的读端口，R6a / R6b 重排，删除 `ReviewView` 相关项；task 层可选审点 R3b 已在 v3.1 记入。

---

## 一、角色（依 `docs/workflow.md`）

| 角色 | 负责 |
|---|---|
| 设计侧（本对话里的 Claude） | 读代码核事实、写 intent / spec / plan、写交接消息、分配 CHANGELOG 编号、验收、裁决停止汇报、**每步验收后提交**（或给用户提交命令） |
| 执行模型 | 在 worktree 里改代码、写测试、跑命令、汇报；**不 add / commit / merge / rebase / reset / stash / checkout** |
| 用户 | 授权真实模拟器 / 真实模型运行与存档重建、在本机跑真机、点头改规范、执行设计侧给的提交命令、最终合入 |

## 二、工作位置

- 仓库：`D:\Users\GummiGu\PycharmProjects\Pokemon_Agent`（Windows，工作区 CRLF、HEAD LF；比对用 `git diff --ignore-cr-at-eol`）。
- 主工作区当前检出的分支以 `.coordination/ledger.md` 为准，常有别的任务的改动。**本系列任务一律不在主工作区做。**
- 分支：`feature/reviewer-transparency-v2`（旧分支 `feature/reviewer-transparency` 已删除，备份 tag `backup/reviewer-transparency-4872093`）；worktree 在仓库内 `.worktrees/reviewer/`。已有提交：`7eb5dba`（R1a，514）、`6a85edd`（R2，515）；基线 `d6e9aaa`（= main）。
- 解释器复用主仓库 `.venv`；worktree 内不运行 `uv run` / `uv sync` / `pip install`；pytest 仅在该 shell 里设 `DEEPSEEK_API_KEY=dummy`，每次自带 `--basetemp`；不复制 `.env` 与任何密钥。
- 新文档：`docs/reviewer/` 三份（intent / spec / plan）由设计侧随 R0 提交入库。

## 三、步骤、依赖与关卡

| 步 | 内容 | CHANGELOG | 依赖 | 完成关卡 |
|---|---|---|---|---|
| R1a | 审点收敛 | 514 ✅（7eb5dba） | 无 | 已验收 |
| R2 | `by` / `answered` 不变式 | 515 ✅（6a85edd） | R1a | 已验收 |
| R0 | 恢复准备：主线合入、重编号、新建 worktree、基线哈希、文档入库 | — ✅ | brain-scope 合入 | 已完成：全量 pytest / slow / ruff 绿；`state_schema_hash()` = `5ea6dffeeb229b7c` 与 main 相同；台账更新 |
| R3 | `ReviewContext`（**不含画面**）+ `frames_of` + `render_context`（按 brain-scope 后的请求形状，带帧处只写张数）+ 四个调用点构造 + `InjectReq` / `AuditReq` 的 `context` 字段 + 文档更新 | 513 ✅（b3e1985） | R0 | 已完成； 四个调用点带 `context`；互斥校验、渲染去重（无 `data:image`）、`frames_of` 去重 / 标签测试（含破坏验证）；`state_schema_hash()` 与 R0 实测起点 `5ea6dffeeb229b7c` 逐位相同 |
| R3b | task 层可选审点（`REVIEW_LAYERS` 默认不含 `task`）：`ReviewContext` 增 `task` 层与 `task_id`；task 层 `review_and_judge` 判成处 audit；`frames_of` 支持 `history` 帧；`build.py` 给 task 层装配 reviewer | 516 ✅ | R3 | 已完成；默认配置下 task 图无 reviewer 调用（行为逐位相同）；开启后的 audit 测试（认账 / 推翻 / 不判成不审，含破坏验证）；新增 TaskState.last_judge，哈希改为 `28e96b09966dc94e`，20 份存档重打与恢复验收 |
| R4 | `elicit_with_review` + AI 轮次阀 + `ReviewMark.capped/round` + config 常量 | 517 ✅ | R2、R3 | 已完成；两层规划共用临时 StateGraph，agent N+1 次不生效但原话落账；人的意见不限轮次并清零；空回话、零上限、跨调用重置与两层入口测试；哈希保持 `28e96b09966dc94e` |
| R5 | 前置核查 → `reviewer/view/` 窄 Protocol、ViewReaders；`schemas/reviewer` 查询模型（含 BrainFramesQuery、run_goal / runs hint） | 518 ✅ | R3 | 已完成；52 项新增测试，真实 MCP 第 12 步取帧、跨进程读取、去图与分页；用户允许派生缓存客观更新，不改记录正文；完整回归 1515 / slow 3 通过；取帧上限与去图两次破坏验证拦截成功；hash 不变 |
| R6a | hub、随问帧分页、schema 派生命令与 help、human 终端、进程内 ReviewerApp、窄协议与导入边界 | 519 ✅ | R4、R5 | 已完成；先答先得、取消与 EOF、快照和历史隔离、命令 ⇔ 类型化调用、慢查询期间答复、旧查询不进入下一问、真实 PNG 输出；新增 52 项，全量 1567 / slow 3 / ruff 通过；两次破坏验证成功，hash 不变 |
| R6b | 单跳线上信封、ReviewLinkServer、RemoteReviewer、独立 human 入口、共享读口装配与 build URL 选择 | 520 ✅ | R6a | 已完成；真实 WS 与独立子进程经 stdin 答复、PNG 查询；qid 重发/离线答复/缓存/取消/占用；已知 AI 超时与其他模式无限等；新增 54 项，默认 1621 / slow 3 / ruff 全绿；两次破坏验证成功，hash 不变 |
| R6c | 删旧栈：`ConsoleReviewer` / `WebReviewer` / `review_backend` / 跳 A·B 信封 / `LiveFeedTrace` 与 `live_feed_url` / 旧常量 / 对应测试 / 文档状态说明 | 529 | R6b | 旧实现符号零残留；新展示接口承接上下文验收；完整回归与哈希验收见 CHANGELOG |
| R7a | 固定 Pydantic AI 2.57.0 为 reviewer optional extra、锁依赖、准备一次性探针 | 530 ✅ | R6c | `uv lock --check` 通过；DeepSeek / Pydantic AI 官方文档已核对；真实模型探针由 R10（534）验收 |
| R7b | 实现进程内 AI 席（Pydantic AI 有界循环、三种模式、讨论与倒计时） | 531 ✅ | R7a 官方接口核查 | 已实现；reviewer 163 项与全量默认测试通过，slow 3 项 / Ruff / 锁文件通过；真实模型结果由 R10（534）验收 |
| R8 | （暂缓）网页入口 | — | R7 | 另行立项 |
| R9 | 文档同步；规范 §四第 3 条修订（须用户点头） | 待分配 | R1a–R7 | 文档与代码一致 |
| R10 | 用户本机真机跑（三种模式） | 534 ✅ | R7 | `deepseek-flash` 图片工具回灌、结构化输出纠正与 usage 通过；本地 WS human / ai / both 均按预期答复；不含共享 trace / memory 服务验收 |
| R1b | 删 `overturned` 字段与读方、结算账 `audit` 键、重建 20 份评测存档 | 待分配 | R1a、**用户另行授权**、评测任务已合入、brain-scope CP8 已完成 | 存档 20/20 真实恢复；`grep overturned` 为空 |
| R11 | 死代码收尾自查（含 `AuditReq.run_id/episode_id` 重复、`brain_goal_judge` 非密闭测试） | 待分配 | 其余全部 | spec §3.4 grep 清单零残留 |

说明：原 R2b（hop-A 线上字段）并入 R6c 一并删除，不再单独做。每步一个提交（由设计侧在验收时提交），提交信息逐字复用 CHANGELOG 条目标题，末尾附协作署名行。

## 四、回退

一步一个提交，回退用 `git revert <提交>`，不重写历史、不 `--amend`、不 force push。R1b 回退还需用 `eval_results/archive_rebuild/` 里的备份还原 20 份存档（执行方在 R1b 开始前必须先备份）。

## 五、CHANGELOG 编号与合入

- 编号由设计侧在派发时分配并记在本表；执行方动手前核对 `git show HEAD:CHANGELOG.md` 顶部编号与分配一致，不一致即停下汇报。
- 编号以 `.coordination/ledger.md` 为准。reviewer 分支上的 R1a / R2 在合入 main 时由 502 / 503 重编号为 514 / 515（避开 memory 已用编号，不改 Git 历史）；R3 起的号恢复时才取。evals/brain-choose-action 的 508–511 继续预留，本次不改其状态。
- 合入前设计侧核对：分支相对基线的提交范围；主线上别的任务是否动了同一批文件（重点：`CHANGELOG.md`、`harness/*/review_and_judge/`、`review_backend/`、`direct/trace/`）。

## 六、停止条件（继承 `docs/workflow.md`，本任务加两条）

- `state_schema_hash()` 相对 R0 实测起点（`5ea6dffeeb229b7c`），在 R1b 之外任何一步变化：立即停下汇报。
- 需要新增 / 修改记忆模块能力面（如新增只读接口）：停下，交用户拍板。
- 需要在 trace 模块新增 `flush` 或其他接口：停下，交用户拍板（R5 核查结果）。
- 引入或升级第三方依赖（R7 的 `pydantic-ai-slim[openai]`）：版本号由设计侧在派发时指定，执行方不得自选。

## 七、遗留清单（合入后另案）

- 若评测发现机械结算误判多，再开「结算复核」。
- 人席也受轮次 / 次数限制的选项（改同一个常量即可，等用户决定）。
- 网页入口（R8）与实时展示项目（从 git 历史取回 `/feed` 相关代码）。
- 将来给 hub 包 MCP 薄壳（供外部 agent 充当 reviewer）。
- `brain_goal_judge` 等测试依赖 `DEEPSEEK_API_KEY` 的非密闭问题。
- task 层的 inject（逐步 `choose` 处插话）：默认不做；若要，先评估阻塞频率，`ChooseOnceReq.human_note` 已是现成入口。
- `read_world`（世界当前状态查询）与多终端同连：v4 取消；若将来要，另案（需先核实世界服务的租约是否允许只读旁路）。
- reviewer 看到的图口径是「⊇ 大脑所见」（不套 `SCOPE_IMAGE_CAP`）；若将来要严格一致，需把 `cap_images` 的取舍结果也记进快照。

---

## 八、与 brain-scope 的关系（2026-10-17 新增）

1. **顺序**：brain-scope 先合入主线，reviewer 之后恢复（用户 2026-10-17 已定，台账同）。brain-scope 已于 2026-10-18 合入（main d6e9aaa），R0 据此执行。
2. **已知文件冲突**（`overlap.py`，2026-10-17）：与 brain-scope 的真冲突候选是 `pokemon_agent/direct/trace/render.py`、`tests/_harness_fixtures/node_io.py`、`tests/harness/run/test_plan_reads_memory.py`；`CHANGELOG.md` 为共享文件。reviewer 分支另与主线冲突于 `review_backend/page.py`、`trace/langfuse_support.py`（MCP-only 与测试瘦身所致）。R0 合并时逐个人工解决，解决提交与重编号提交分开。
3. **请求形状**：R3 起一律以合入后的代码为准（spec 4.1 为依据，字段名待核）；`ReviewContext.brain_input` 保留三类请求，图经 `frames_of` / `read_brain_frames`。
4. **哈希与存档**：brain-scope 的 CP8 已重打 20 份评测存档（501），`state_schema_hash()` 已定型为 `5ea6dffeeb229b7c`。R3b 经用户 2026-10-18 授权新增 TaskState.last_judge，哈希改为 `28e96b09966dc94e` 并重打 20 份存档；R1b 之后仍需按最终结构另行重打。
5. **可提前的部分（待核）**：设计文档（本版）已同步，不占执行方。代码步骤里 R5 现在只新增 `reviewer/view/` 与 `schemas/reviewer/` 下的新文件，几乎不改既有文件，与 brain-scope 的文件交集预计为零；但它依赖 brain-scope CP1 的召回新取法（`run_goal` / `runs`）与 R3 的 `frames_of`，所以**默认等 brain-scope 合入**（现已满足，R5 排在 R3 之后）；派发前须对 R5 的精确文件清单跑 `overlap.py --branch`。
6. **R3b 与 brain-scope CP3 同一处**：R3b 改 task 层 `review_and_judge`，brain-scope CP3 已改过它（取全部 ActMemory、`task_index`），所以 R3b 只能在 brain-scope 合入之后做，以合入后的形状为准。
