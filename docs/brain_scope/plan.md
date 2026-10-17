# plan —— 大脑感知范围（brain_scope）

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

**CP5（489）** `harness/episode/`（`perceive/`、`episode_state.py`、`plan_episode/`、`review_and_judge/`）、`schemas/harness/communication/` 的 `DecomposeReq` / `JudgeReq`、`direct/prompts/`（`decompose`、`judge_success`）、测试

**CP6（490）** `harness/run/`（`perceive/read_plan_context.py`、新增知识检索格、`run_state.py`、`plan_run/`、`review_and_judge/`）、`schemas/harness/communication/` 的 `PlanOnceReq` / `JudgeReq`、`direct/prompts/`（`run_plan`、`judge_success`）、测试

**CP7（491）** `pokemon_agent/config.py`（`max_episodes`）、`tests/budget/test_run_config.py`、`docs/budget/run-budget-spec.md`、`docs/spec/build/SPEC.md`、`docs/spec/DATAFLOW.md`、新增集成测试、残留扫描涉及的文件

## 五、每个检查点我的核对点

见 spec 第三节检查点表的『我的核对点』一列，另加三条通用的：
1. `git diff --stat` 与允许文件清单逐文件对照，CRLF / LF 无整文件翻转（`git diff --ignore-cr-at-eol`）；
2. 汇报的 pytest、`ruff check`、`ruff format --check` 尾行与我自己重跑的一致；
3. 汇报的实测 `state_schema_hash` 记录进本文第九节。

## 六、与并行任务的关系（`overlap.py` 与台账）

- `chore/test-reclass`（484）：搬移 integration 下 2 个文件、删 2 个无用测试、测耗时。与本项目的文件交集目前为空；两边都会往 `CHANGELOG.md` 顶部插条目，合并时在集成分支里保留两边条目、按编号排序，用单独整理提交解决，不改编号。
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

## 十、PR 组织与合入

整个分支一个 PR（或用户直接合并），提交顺序即检查点顺序；合入由用户做。合入前我核对分支相对 `ce1e9c3` 的提交范围，以及主线之后别的任务是否动了同一批文件。

## 十一、合入后遗留清单

1. `max_episodes = 10` 的取值依据待真实运行产出记忆后复核长度（spec D11）。
2. L2 索引按目标文本逐字相等匹配：模型重拆时改写了目标文字，索引就为空（spec D7 已知限制，不做模糊匹配）。
3. `SCOPE_IMAGE_CAP = 20` 是实验旋钮，待真实运行后看是否需要调。
4. 异常上抛的 run 不写 RunMemory（spec Q10）；若将来要求异常也落空章，另案处理。
5. reviewer 恢复时的 CHANGELOG 重编号与 `render_context` 适配。
