# plan —— 大脑感知范围（brain_scope）

> 2026-10-19 更正：L1 改为按本 run 的 L1 goal 身份召回背景，见 spec 顶部更正；
> 下文 CP1–CP8 是历史实施记录，其中 run_goal 等值／跨 run 方案已被本次更正替代。

> 状态：CP1–CP8 已完成（2026-10-18）；存档验收与收尾见第十三节。

> 流程位置：intent（已确认）→ spec v1.3（Q1–Q9 已确认）→ **plan.md（本文）** → 落码
> 依据：`docs/brain_scope/spec.md`（执行依据；本文与它不一致时以 spec 为准）、`docs/brain_scope/intent.md`。
> 基线：分支 `feature/brain-scope`，worktree `.worktrees/brain-scope`，基于主线 `ce1e9c3`（CHANGELOG 顶号 483）；第一个提交 `bf7c7c0` 是 intent / spec / workflow 三份文档。

## 一、角色

- 设计侧（我）：核实、写文档、分配编号并登记台账、发交接、验收、提交、更新台账。不写生产代码。
- 执行方：只改代码与测试、按给定编号写 CHANGELOG、汇报；不提交，不建/删 worktree。
- 用户：确认费用、CP8 在本机重打存档并清空旧记忆、把分支合入主线。

## 二、检查点顺序与依赖

严格串行，一个检查点一次验收、一个提交；同一分支同一 worktree。

| CP | 编号 | 内容 | 依赖 |
|---|---|---|---|
| CP1 | 485 | 基建与记忆侧（ruff 排除 `.worktrees`、`EpisodeMemory` 三字段、`RunMemory`、三个 `index_line`、kind `run` 的存储 / 召回 / restore、两种召回新取法） | 无 |
| CP2 | 486 | 写入侧（`run_goal` 传递与盖章、run 蒸馏链路、两个新格与 `run_graph` 条件边、降级、三本账） | CP1 |
| CP3 | 487 | L2（plan_task / task judge 取全部、`task_index`、`$knowledge`、删两个窗口常量、`SCOPE_IMAGE_CAP`、`cap_images`） | CP2 |
| CP4 | 488 | 图通道（`BrainPort.plan` / `decompose` 加 `images`） | CP3 |
| CP5 | 489 | L1（`retrieve_episode_index`、`episode_index`、`judge·L1` 字段、L1 带图、删 `global_episode_memories`） | CP1、CP4 |
| CP6 | 490 | L0（详情全部 + `run_index`、run 层知识检索、L0 带图、删 `_pick_details` 与 `index`） | CP1、CP2、CP4 |
| CP7 | 491 | 预算与集成（`max_episodes` 10、FakeLLM 范围一致性集成测试、残留扫描、文档同步） | CP1–CP6 |
| CP8 | 492（预留，存档重打若需 CHANGELOG 条目才用） | 用户在本机重打存档、清空旧记忆；设计侧核对结果 | CP7 |

## 三、编号台账

478–483 已用；484 预留给 `chore/test-reclass`。本项目 485–491 依次占用；**每个号先写进 `.coordination/ledger.md` 的『编号』表，再发对应交接**。被驳回或作废的号标『空号』，不回收。

## 四、各检查点允许改动的文件

> CP1、CP2 精确到文件；CP3–CP7 先按目录写，**派发该检查点时我再细化到文件并再跑一次 `overlap.py`**。任何检查点都不得改 `CLAUDE.md` / `AGENTS.md`。每个检查点都含 `CHANGELOG.md` 与该检查点自己新增 / 必须调整的测试。

**CP1（485）**
- `pyproject.toml`（只改 ruff `extend-exclude`，加 `.worktrees`）
- `pokemon_agent/schemas/memory/datastore/`：`episode_memory.py`、`task_memory.py`、新增 `run_memory.py`、新增 `index_text.py`（首句规则）、`__init__.py`；`pokemon_agent/schemas/memory/__init__.py`
- `pokemon_agent/memory/recall.py`、`pokemon_agent/memory/store.py`
- `pokemon_agent/schemas/harness/communication/`：`FromHarnessToMemoryToolMemorizeReq.py`、`FromHarnessToMemoryToolRecallReq.py`（只改说明）、`FromHarnessToMemoryToolRecallResp.py`
- `pokemon_agent/mcp_servers/memory_server.py`（只改工具说明）、`pokemon_agent/mcpclient/memory_local.py`（只改 docstring）
- `docs/spec/memory/SPEC.md`（『五类』→『六类』）
- 新增测试：`tests/memory/test_memory_index_lines.py`、`tests/memory/test_run_memory_family.py`；既有测试只允许为适配 Literal / 字段默认值做最小调整，并在汇报里逐个列出

**CP2（486）**
- `pokemon_agent/schemas/harness/domain/episode_io.py`（`EpisodeInput.run_goal`）、`pokemon_agent/schemas/harness/domain/trace_kind.py`（三个新 kind）
- `pokemon_agent/schemas/harness/communication/`：新增 `FromHarnessToBrainToolSummarizeRunReq.py` / `Resp.py`、`__init__.py`
- `pokemon_agent/brain/`：`interface/brain_port.py`、新增 `interface/domain/run_summary.py` 及其出口、`brain.py`、`providers.py`（若接线需要）
- `pokemon_agent/direct/`：`brain_tool.py`（`RunSummarizer`）、`interface/ports.py`（`RunSummarizePort`）、`prompts/summarize_run.py`、`prompts/calls/summarize_run.md`、`trace/content.py`、`trace/render.py`
- `pokemon_agent/harness/run/`：`run_graph.py`、新增 `summarize_run/`、`store_run_memory/`、`runtime.py`、`act/dispatch.py`（传 `run_goal`）
- `pokemon_agent/harness/episode/`：`episode_state.py`、`episode_done/` 下盖章与空章处（`summarize_episode.py`、`leave_chapter.py`）
- `pokemon_agent/build.py`（注入 `RunSummarizePort`）
- `docs/spec/DATAFLOW.md`（事件总表补三本账）
- 测试：新增 / 调整见 spec 第五节

**CP3（487）** `pokemon_agent/config.py`、`harness/task/`（`plan_task`、`review_and_judge`、`task_state.py`、`task_entry.py`）、`harness/episode/act/dispatch_task.py`、`schemas/harness/domain/task_io.py`、`schemas/harness/communication/` 的 `ChooseOnceReq` / `JudgeReq`、`direct/brain_tool.py`（`cap_images`）、`direct/prompts/`（`decide_action`、`judge_success` 及其 `.md`）、`schemas/memory/datastore/act_memory.py`（仅一处注释）、`build.py`（装配期断言）、`docs/spec/build/SPEC.md`、测试

**CP4（488）**（CP3 裁定：run 蒸馏带图从 CP2 顺延到本检查点，`BrainPort.summarize_run` 加 `images` 并过 `cap_images`；`task_index` 住 `TaskState` 顶层而非 `task_ctx`）`brain/interface/brain_port.py`、`brain/brain.py`、`brain/providers.py`（若需要）、`direct/brain_tool.py`（`Planner` / `Decomposer`）、`direct/interface/ports.py`、mock 与相关测试

**CP5（489）**（派发时细化）`harness/episode/`：`perceive/retrieve_global_episode_memory.py` 改名 `retrieve_episode_index.py`、`perceive/__init__.py`、`perceive/merge_retrieval.py`（仅 docstring）、`episode_state.py`（`EpisodeContext.global_episode_memories` → `episode_index`）、`plan_episode/plan_episode.py`、`review_and_judge/__init__.py`；`schemas/harness/communication/` 的 `FromHarnessToBrainToolDecomposeReq.py`（`episode_memories` → `episode_index`）与 `FromHarnessToBrainToolJudgeReq.py`（加 `episode_index`、`observation`）；`direct/brain_tool.py`（仅 `Judger` 的 L1 带图）、`direct/prompts/decompose.py`、`direct/prompts/judge_success.py`、`direct/prompts/calls/judge_success.md`；`tests/_harness_fixtures/node_io.py` 与相关测试（含冻结哈希测试的常量）；`docs/spec/DATAFLOW.md`、`docs/spec/harness/SPEC.md`、`docs/spec/schemas/SPEC.md`、`docs/eval/tasks-intent.md`（仅字段名处）；`CHANGELOG.md`。**本检查点状态哈希预期变化**（`ep_ctx` 字段改名与描述）。

**CP6（490）**（派发时细化）`harness/run/`：`perceive/read_plan_context.py`、新增 `perceive/retrieve_run_knowledge.py`、`perceive/__init__.py`、`run_state.py`（`PlanContext` 去 `index`、加 `run_index` / `knowledge`）、`plan_run/plan_run.py`、`review_and_judge/review_and_judge.py`；新增共享的 `harness/knowledge_query.py`（`build_knowledge_query` 迁入，episode 的 `retrieve_knowledge_semantic_memory.py` 改为从它导入）；`schemas/harness/communication/` 的 `FromHarnessToBrainToolPlanOnceReq.py`（删 `index`，加 `run_index` / `knowledge` / `observation`）与 `FromHarnessToBrainToolJudgeReq.py`（加 `run_index`）；`direct/brain_tool.py`（仅 `Judger` 的 L0 带图）、`direct/prompts/run_plan.py`、`direct/prompts/judge_success.py`、`direct/prompts/calls/run_plan.md`、`calls/judge_success.md`；`tests/_harness_fixtures/node_io.py` 与相关测试（含冻结哈希常量）；`docs/spec/DATAFLOW.md`、`docs/spec/harness/SPEC.md`；`CHANGELOG.md`。**本检查点状态哈希预期变化**（`PlanContext` 字段）。

**CP7（491）**（派发时细化）`pokemon_agent/config.py`（仅 `max_episodes` 50→10）、`tests/budget/test_run_config.py`、`docs/budget/run-budget-spec.md`（D1 / D11 / 预算表三处的 50）、`docs/spec/build/SPEC.md`（约 102 行的 50）、`docs/spec/DATAFLOW.md`（约 60 行的 50）、新增 `tests/integration/test_brain_scope_consistency.py`（范围一致性集成测试，验收 1、2、4、6、7）、残留扫描命中的现行代码 / 测试 / 文档（仅限清残留，不扩功能）、`CHANGELOG.md`。起点与终点各跑一次 `-m slow`（终点那次兼作 CP8 前的那次）。哈希预期不变。

## 五、每个检查点我的核对点

见 spec 第三节检查点表的『我的核对点』一列，另加三条通用的：
1. `git diff --stat` 与允许文件清单逐文件对照，CRLF / LF 无整文件翻转（`git diff --ignore-cr-at-eol`）；
2. 汇报的 pytest、`ruff check`、`ruff format --check` 尾行与我自己重跑的一致；
3. 汇报的实测 `state_schema_hash` 记录进本文第九节。

## 六、与并行任务的关系（`overlap.py` 与台账）

- `chore/test-reclass`（484 / 493 / 494 / 495，测试瘦身）：**已合入本分支**（合并提交 `1a16806`，合入的是 `5964222`，不是带快照提交 `97647a9` 的 `main`）。冲突两处：`CHANGELOG.md` 两边条目按编号降序并存；`tests/integration/test_harness_integrity.py` 主线已删，取删除。影响见第十二节。
- `feature/reviewer-transparency`（暂缓）：**本项目先合入**，reviewer 恢复时以合入后的请求形状为准；其 CHANGELOG 460 / 461 与主线冲突，恢复时统一重编号。
- 主线新增提交碰到本分支文件时，我在下一次验收时把主线 merge 进来（不 rebase），并在台账记一笔。

## 七、回退方式

一个检查点一个提交，回退用 `git revert <该提交>`，不重写历史。CP2 之后的检查点依赖前面的，要回退中间某个时按相反顺序依次 revert。文档提交 `bf7c7c0` 不回退，修订用新版本号的新提交。

## 八、耗时与费用

- 全部自动测试，不调真实模型、不用模拟器，没有模型费用。
- 粗估执行量：CP1、CP2 最重（新增一级记忆与一条模型调用链路），CP3、CP5、CP6 中等，CP4、CP7 较轻；每个检查点一次验收。
- CP8 在用户本机，需要 ROM / 模拟器，由用户确认。

## 九、实测哈希记录（每个检查点验收后回填）

| 时点 | `state_schema_hash` | 备注 |
|---|---|---|
| `352af88`（spec v1.2 时） | `4f1cac6fcc7216d5` | 探针 |
| `ce1e9c3` 起点 | `4f1cac6fcc7216d5` | CP1 执行方实测，与探针一致 |
| CP1 终点 `01d66de` | `1da60900e11478a0` | EpisodeMemory 加三字段 |
| CP2 终点 `161a155` | `3c713ab4487ef650` | 变化来自首末帧描述、EpisodeInput.run_goal、RunState.run_memory |
| CP3 终点 `0a34982` | `ef3ba958c2680260` | 变化仅来自 TaskState.task_index |
| CP4 终点 `9a88439` | `ef3ba958c2680260` | 不变（只改 docstring 与 brain 方法签名） |
| CP5 终点 `c58171a` | `d8fa15ee4072f698` | 仅来自 EpisodeContext.global_episode_memories → episode_index 及描述 |
| CP6 终点 `3839339` | `5ea6dffeeb229b7c` | 仅来自 PlanContext（去 index，加 run_index / knowledge） |
| CP7 终点 `0f29078` | `5ea6dffeeb229b7c` | 不变 |

## 十、PR 组织与合入

整个分支一个 PR（或用户直接合并），提交顺序即检查点顺序；合入由用户做。**本分支现在含 `chore/test-reclass` 的 4 个提交**（经 `1a16806` 合入）：`chore/test-reclass` 与本分支要么先后合入 `main`（先合 `chore/test-reclass`，再合本分支），要么一起合；`main` 上的快照提交 `97647a9` 不得带进来。合入前我核对分支相对 `ce1e9c3` 的提交范围，以及主线之后别的任务是否动了同一批文件。

## 十一、合入后遗留清单

1. `max_episodes = 10` 的取值依据待真实运行产出记忆后复核长度（spec D11）。
2. L2 索引按目标文本逐字相等匹配：模型重拆时改写了目标文字，索引就为空（spec D7 已知限制，不做模糊匹配）。
3. `SCOPE_IMAGE_CAP = 20` 是实验旋钮，待真实运行后看是否需要调。
4. 异常上抛的 run 不写 RunMemory（spec Q10）；若将来要求异常也落空章，另案处理。
5. reviewer 恢复时的 CHANGELOG 重编号与 `render_context` 适配。

## 十二、测试瘦身合入后的调整（2026-10-17 晚，合并提交 `1a16806`）

**1. 基线**：从 CP4 起，起点是合并提交 `1a16806` 之后的文档提交 `40c1849`（含瘦身后的全部测试，本节即在该提交里）。生产代码只多了 `rules.py` 一行注释，状态哈希应仍为 `ef3ba958c2680260`。

**2. pytest 的新事实**
- 默认 `addopts` 带 `-m "not slow"`（`pyproject.toml`）；默认全量约 1192 例（本分支新增测试另计）、约 75–90 秒。
- `slow` 只有 `tests/harness/checkpoint/test_checkpoint_restore.py` 的 3 例（整图 + 存档恢复，约 110 秒），用 `python -m pytest -m slow` 单独跑，**默认不跑**。
- 本项目 CP2 起改了 run 图（8 格）、`RunState`（`run_memory` 槽）与 `EpisodeInput`（必填 `run_goal`），存档恢复正好经过这些，而默认套件已不覆盖它。所以：**CP4 起点补跑一次 `-m slow`**，之后 **CP7 与 CP8 前各再跑一次**。失败即停下汇报，由我另分配 CHANGELOG 号处理，不并入当前检查点。

**3. 路径对照（交接消息里的既有测试清单按此改）**
- `tests/integration/test_node_io.py` → `tests/harness/ledger/test_node_io.py`。
- `tests/harness/task/test_p6_event_alignment.py` → `test_step_and_script_event_alignment.py`。
- 已删，不再调整：`tests/integration/test_harness_integrity.py`、`test_p5_script_actions.py`、`test_web_reviewer_integration.py`、`tests/review_backend/*`、`tests/assembly/test_build.py`、`test_run_result.py` 里两个整图用例、`test_no_eval_knobs.py`。
- 这些的断言里原有的「计入 run 记忆」「ChooseOnceReq」等适配不必再补。`tests/integration/` 目录现为空，但 `AGENTS.md` 的约定「跨模块的端到端放 `tests/integration/`」仍有效，CP7 的范围一致性集成测试仍放那里。

**4. 本项目新增测试的约束（承接瘦身判据：非单元测试且不被其他测试覆盖的删，所以我们只留必要的）**
- 优先单元。整图跑的只留两处唯一守卫：CP2 的 `test_run_summary_cells_run_after_done_in_a_full_graph_run`（防两格被 `guarded` 跳过）与 CP7 的范围一致性集成测试。
- 整图测试一律 `run_fake(checkpoints=False)` 或等价的无存档装配，目标单个用例 5 秒内；不标 `slow`。若实测超过 20 秒，停下问我是标 slow 还是改写。
- 每个检查点汇报里加一项：本检查点新增 / 调整的测试文件的 `--durations=10` 前十行。
- CP4 起点另做一次：对 `tests/memory/test_memory_index_lines.py`、`test_run_memory_family.py`、`tests/harness/run/test_run_memory_write.py`、`tests/harness/episode/test_episode_scope_stamp.py`、`tests/harness/episode/test_task_index_dispatch.py`、`tests/harness/task/test_task_scope*.py`、`tests/brain/summarize/`、`tests/direct/` 下 CP2 / CP3 新增的文件跑 `--durations=0`，汇报总耗时与最慢三例，我据此决定是否要瘦。

**5. 顺序与编号不变**：CP4（488）→ CP5（489）→ CP6（490）→ CP7（491）；CP8（492）预留。台账里 493–495 已被 `chore/test-reclass` 占用，下一个空号 496，留给合入后补修用。

## 十三、CP8 验收与收尾（2026-10-18）

- 已重打 20 份 v1 起点存档：`state_schema_hash` 统一为 `5ea6dffeeb229b7c`，`plan_ctx` 均为 null。
  全部源 `.state` 哈希与数据集冻结值一致；同源样本的新 world.state 仍保持一致。
- 对比重打前 HEAD：13 份 world.state 改变、7 份不变。用户接受此差异，不再追查历史原因；
  战斗菜单样本 A/B 重打实验哈希相同，证据及其边界记录在 CHANGELOG 496。
- 固化 20 份 manifest、13 份变化的 world.state、20 份当前引用的快照；清理 20 份旧的已跟踪
  快照及额外一次单样本重打留下的未引用快照。此前指定的 3 份试打快照已清理。
- 租约缺陷已由 `c222dcc` 修复：失败信封立即报错，pack 成功或异常退出均尝试释放租约。
  两个独立进程采用默认身份实测成功，退出后租约为空，起点哈希符合预期。
- 用户已授权本次完成清理、提交与主线合入；采用 fast-forward，禁止带入的 `97647a9` 不在
  本分支历史中。world / memory 服务及仓库外专用记忆目录保留。
- eval、reviewer 与测试重写不属于本次收尾，另行开始；其他测试 worktree 不改动。

- 收尾全套 pytest（含 slow）：1316 passed（109.44s，1 条 SDL2 版本提示）；ruff check / format 通过。
