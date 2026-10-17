# spec —— 大脑感知范围（brain_scope）

> 流程位置：intent（已确认）→ **spec.md（本文，v1.3，Q1–Q9 已由用户确认）** → plan → 落码
> v1.1 修订原因：按用户澄清收紧两条索引的口径——L1 = 被同一 `run_goal` 绑定的 episode（跨 run 只因同一目标被重新发起）；L2 = 本 episode 内目标文本相同的此前 task。
> v1.2（2026-10-16）修订原因：主线已用 CHANGELOG 478 删除 `max_summaries` 与 `_trim_episodes`（局摘要数量上限），不再有全局淘汰；D4、D6、第八、九、十一节中依赖淘汰的表述同步更正，Q5 消解；本项目 CHANGELOG 编号改从 480 起（478 为 cap 删除，479 为 mcp-only 批 ①）。
> v1.3（2026-10-17）修订原因：基线从 `352af88` 前移到主线 `ce1e9c3`（MCP-only 批 ①–③b 已合入），记忆侧引用对新代码逐项重核。D5：Req 字段名对齐 `RunResp`（只有 `total`，没有 `acts_used`），run 蒸馏的位置改为 `run_done` 之前的两个新格，并写明收尾路径核实结果；D6：kind 命名（存储 `run_memory`、对外 `run`）、两处 Literal、`memorize` 分发、`restore` 重读循环逐项对齐新代码，『列出 run 级记忆』的 hint 由 `kind` 改 `runs`（`RecallReq` 约定 conditions 不放 kind）；D3 / Q8：按用户 2026-10-17 的决定，旧 episode 直接删除、不写兼容逻辑；编号改从 485 起（484 预留给测试瘦身）；Q1–Q9 回写。
> 依据：`docs/brain_scope/intent.md`。基线：分支 `feature/brain-scope`，提交 `ce1e9c3`（主线 `main`，CHANGELOG 顶号 483，MCP-only 全部合入）；分支于 2026-10-17 把 `ce1e9c3` merge 进来。
> 基线数值：`state_schema_hash = 4f1cac6fcc7216d5`（MCP-only 期间没有改状态模型，预计不变；v1.3 沙箱没有项目依赖，**未复测**，CP1 起点由执行方在项目 venv 实测并汇报）；`CHANGELOG.md` 顶号 483；全部调研以该提交的代码为准（读码 + 探针，见第九节）。
> 本文是**设计改动的完整清单**；Q1–Q9 已于 2026-10-17 确认，之后写 plan、按检查点派发。

---

## 零、一页总览

**一条规则，三处套用**：每次大脑调用只读它所服务的目标所绑定的单元——详情 = 该单元下全部下一级子单元记忆；背景 = 同级过往单元的一行索引；生成者与 judge 读同一份。

| 调用点 | 绑定单元 | 详情（全部） | 背景索引（一行一条，不含本单元） | 图 |
|---|---|---|---|---|
| `plan·L0` / `judge·L0` | run | 本 run 全部 EpisodeMemory | 过往的 run（RunMemory，不按 `run_goal` 限制） | 每局首末帧 |
| `plan·L1` / `judge·L1` | episode | 本 episode 全部 TaskMemory | 被同一个 `run_goal` 绑定的 episode（`run_goal` 文本相等，不含本局）。同一目标一次跑不完被重新发起时，这些 episode 会分布在多个 run 里，「跨」只因此而来 | 每 task 首末帧 |
| `plan·L2` / `judge·L2` | task | 本 task 全部 ActMemory | 本 episode 内、目标文本与本 task 相同的此前 task 的 TaskMemory（不含本 task） | 每步前后帧（去重） |

六处另给**知识**与**当前 RAM 现状**。

**记忆阶梯多一级**：Act → Task → Episode → **Run**。RunMemory 与另两级同构：harness 盖来源章 + LLM 蒸馏正文，成败只认章，可重建可丢弃。

**同步发生的改动**：删两个窗口常量；`max_episodes` 默认 50 → 10；`EpisodeMemory` 加 `run_goal` 与首末帧；召回口加两种取法；`BrainPort.plan` / `decompose` 加 `images`；新增 run 级蒸馏链路；评测存档因状态哈希变化要重打。

---

## 一、逐调用点：请求字段的增 / 删 / 不变

> 下表的「现状」均已对基线读码核对；字段名以代码为准，新增字段名为拟定。

### 1.1 `plan·L0`（`FromHarnessToBrainToolPlanOnceReq`，`plan_run` 发出）

| 字段 | 现状 | 新 |
|---|---|---|
| `plan`（目标表） | 有 | 不变 |
| `index` | 本 run 全部局，渲染成每局一行 | **删**：本 run 的局全部进 `details`，两处传同一东西违背「prompt 是规则、入参是素材」 |
| `details` | `_pick_details`：最近 1 局 + 全部失败局 | **改**：本 run 全部 EpisodeMemory，按执行序 |
| `run_index` | 无 | **增** `list[RunMemory]`：过往 run，一行一条，不含本 run |
| `objects` | 有（本 run 的地图交互事实） | 不变 |
| `knowledge` | 无（run 层没有知识检索） | **增** `list[str]` |
| `observation` | 无 | **增** `TaskObservation \| None`（`RunState.observation`，RAM 现状） |
| `last_judge` / `max_push` / `human_note` | 有 | 不变 |
| 图 | 无（`BrainPort.plan` 没有 `images`） | **增**：`details` 每局的 `first_frame` / `last_frame` |

### 1.2 `judge·L0`（`FromHarnessToBrainToolJudgeReq`，run 层 `review_and_judge` 发出）

| 字段 | 现状 | 新 |
|---|---|---|
| `goal` | `run_goal` | 不变 |
| `episode_memories` | `plan_ctx.index`（本 run 全部局，渲染全文） | **改**：与 `plan·L0` 的 `details` 是**同一份对象** |
| `run_index` / `knowledge` / `observation` | 无 | **增**（同 `plan·L0`） |
| 图 | 无 | **增**：同 `plan·L0` |

### 1.3 `plan·L1`（`FromHarnessToBrainToolDecomposeReq`，`plan_episode` 发出）

| 字段 | 现状 | 新 |
|---|---|---|
| `goal` / `observation` / `task_table` / `knowledge` / `last_judge` / `max_tasks` / `human_note` | 有 | 不变 |
| `task_memories` | 本 episode 全部 TaskMemory（`retrieve_task_memories`，按 `episode_id` 召回） | 不变，即详情 |
| `episode_memories` | 本 run 全部局的 EpisodeMemory，渲染全文（`retrieve_global_episode_memory`，按 `run_id` 召回） | **改名为 `episode_index`**：`run_goal` 与本 run 相同的 episode，**渲染成一行**，不含本局 |
| 图 | 无（`BrainPort.decompose` 没有 `images`） | **增**：`task_memories` 每条的 `first_frame` / `last_frame` |

### 1.4 `judge·L1`（同一 `FromHarnessToBrainToolJudgeReq`，episode 层 `review_and_judge` 发出）

| 字段 | 现状 | 新 |
|---|---|---|
| `goal` / `task_memories` / `task_table` | 有 | 不变；`task_memories` 与 `plan·L1` 是同一份对象 |
| `episode_index` / `knowledge` / `observation` | 无 | **增** |
| 图 | 无 | **增**：同 `plan·L1` |

### 1.5 `plan·L2`（`FromHarnessToBrainToolChooseOnceReq`，`plan_task` 发出）

| 字段 | 现状 | 新 |
|---|---|---|
| `goals` / `obs` / `space` / `last_result` / `knowledge` / `human_note` | 有 | 不变 |
| `memories` | `act_memories[-CHOOSE_HISTORY_STEPS:]`（最近 8 条） | **改**：本 task 全部 ActMemory |
| `task_index` | 无 | **增** `list[TaskMemory]`：本 episode 内、`goal` 与本 task 相同的此前 task（去掉两张帧），一行一条 |
| `episode_memories: str` | 有字段与 `$episode_memories` 占位符，**`plan_task` 从不赋值**，恒为「（无跨局摘要）」 | **删**（陈旧项，读方清零后删，见 D12） |
| 图 | `dedup_snapshots(memories)` | 不变（现在是全部 `memories`） |

### 1.6 `judge·L2`（同一 `FromHarnessToBrainToolJudgeReq`，task 层 `review_and_judge` 发出）

| 字段 | 现状 | 新 |
|---|---|---|
| `goal` / `allow_interrupt` | 有 | 不变 |
| `history` | `act_memories[-JUDGE_HISTORY_STEPS:]`（最近 3 条） | **改**：本 task 全部 ActMemory，与 `plan·L2` 是同一份对象 |
| `task_index` / `knowledge` | 无 | **增** |
| `observation` | prompt 的 `$observation` 由 `history` 最后一条的 `after` 渲染（`judge_success.py`） | **不增字段**：全部 `history` 的最后一条 `after` 就是当前 RAM 现状 |
| 图 | `dedup_snapshots(history)` | 不变（现在是全部） |

---

## 二、决定表

### D1 三层的「范围对象」：perceive 装一份，plan 与 judge 读同一份

- 每层只有 `perceive` 读记忆（现有铁律）。三层的上下文对象即「范围」：run 层 `PlanContext`、episode 层 `ep_ctx`、task 层 `task_ctx`。
- 同一层的 `plan_*` 与 `review_and_judge` **从同一个上下文对象取详情与索引**，不各自再取、不各自截取。这样验收 1（详情条数相同）由构造成立，而不是靠两边各写一遍再对齐。
- 取舍：不新建「Scope」总类，复用现有上下文对象——新类要同步改三张状态图，且与现有 `PlanContext` / `ep_ctx` / `task_ctx` 重复。代价：三个上下文对象各自加字段，字段名在 1.x 节统一。

### D2 索引行：三个 `index_line()`，挂在数据形状上

「渲染跟着数据形状放」：`EpisodeMemory.index_line()`、`TaskMemory.index_line()`、`RunMemory.index_line()` 三个纯函数，与同类的 `render()` 并列；**不调模型、不读外部状态**。

**首句规则（确定性）**：取 `summary` 去首尾空白后，到第一个 `。` `！` `？` `.` `!` `?` 或换行为止（含该标点）；超过 80 个字符时截成前 80 个字符并追加 `…`；`summary` 为空则写 `（无正文）`。

**行格式**（`｜` 为全角竖线；`成功/未成功` 取自 `.success`，即 `termination == "goal_done"`；`termination` 为空写 `-`）：

```
episode: - {episode_id}｜{goal}｜{成功|未成功}｜{termination}｜{steps} task/{acts_used} 键｜{首句}
task:    - {task_id}｜{goal}｜{成功|未成功}｜{termination}｜{steps_used} 键｜{首句}
run:     - {run_id}｜{run_goal}｜{succeeded}/{episodes} 局成功｜{termination}｜{首句}
```

固定样例（进测试，整行断言相等）：

```
EpisodeMemory(episode_id="r1-ep2", goal="走到门口并进去", termination="goal_done", steps=3, acts_used=17,
              summary="从野外绕到门口后进入室内。之后又在室内走了几步。")
→ - r1-ep2｜走到门口并进去｜成功｜goal_done｜3 task/17 键｜从野外绕到门口后进入室内。
```

**红线**：行内只出现来源章字段与 `summary` 的首句；我们拼的部分不写「没变化」「撞墙」这类结论（ActMemory 的既有红线）。`summary` 首句是模型写的，测试管不到其内容，只管取法。act 级索引取消（三级里没有消费者）。

### D3 `EpisodeMemory`：加 `run_goal` 与首末帧

- 新字段：`run_goal: str = ""`（来源章，默认空以读旧文件）；`first_frame: str | None = None`、`last_frame: str | None = None`（PNG data URI）。
- **盖章点**：`Summarizer.summarize()` 组装 EpisodeMemory 处，与 `store_empty_chapter()`（空章）。首末帧 = `ep_ctx.task_memories` 第一条的 `first_frame` 与最后一条的 `last_frame`（按执行序）；缺帧为 `None`；不调模型。
- `run_goal` 的来源：`EpisodeInput` 新增 `run_goal: str`，由 run 层 `dispatch` 从 `RunState.run_goal.goal` 填入；经 `EpisodeRunState` 到盖章点。空章（整局异常，由 run 层 `act` 代写）同样盖。
- 落盘：`_memorize_episode` 的元数据加 `"run_goal"`（供召回等值筛选）。`payload` 照旧 `model_dump(exclude={"markdown"})`，首末帧随 payload。
- 旧文件（Q8，用户 2026-10-17 定）：**不为旧数据写任何兼容逻辑**。三个字段保留默认值，只因 pydantic 缺字段本就按默认读、改必填会连带改全部测试夹具；没有 `run_goal` 的旧 episode 不会被 `run_goal` 等值筛选命中（筛选值恒非空），旧记忆在 CP8 重打存档时随整库清空。

### D4 `RunMemory`：新增一级，蒸馏正文

- 归属 `schemas/memory/datastore/run_memory.py`（与另三级并列，经 `schemas.memory` 统一出口）。
- **来源章**（harness 盖）：`run_id`、`run_goal`、`episodes`（局数）、`succeeded`（成功局数）、`acts_used`（累计按键）、`termination`（run 层终止类别）、`reason`（本 run 蒸馏时 LLM 写的结论说明，空章为异常摘要）。`succeeded` / `episodes` 取自 `RunResp`（结算时点的真值），**不事后从 episode 反推**——`RunResp` 是结算时点的真值，反推要依赖 episode 记忆恰好齐全。
- **派生正文**（LLM 蒸馏）：与 EpisodeMemory 同形——`summary`、`reusable_patterns`、`critical_decisions`、`failure_points`、`quality_score`、`quality_rationale`、`applicable_scenes`、`tags`、`markdown`。
- 同样的三条推论：成败只认章（`.success` 由 `termination == "goal_done"` 推出）；可重建；可丢弃。「一个 run 恰好一条」是硬约束：蒸馏失败或没有可蒸的 EpisodeMemory 时落一条只有来源章、正文为空的记录（`quality_rationale` 写原因），与 `store_empty_chapter` 同一套做法。
- `render()` 与 `index_line()`：`render()` 供召回打分与全文展示，`index_line()` 见 D2。

### D5 run 级蒸馏链路（新增的一次模型调用）

- **brain 侧**（对外接口变化，需用户确认，见第十一节 Q）：`BrainPort` 新增第八个方法 `summarize_run(...)`，形状同 `summarize`：`prompt`（规则）+ 素材 + 可选 `images`；返回 brain 方言的 `RunSummary`（字段与 `EpisodeSummary` 同名同形）。`Brain` 实现、mock、`providers` 接线随之。
- **信封**：`FromHarnessToBrainToolSummarizeRunReq` / `Resp`（住 `schemas/harness/communication/`，From/To 放发起方，内嵌 `RunSummary` 的 Resp 由 `BrainTool` 组装出 `RunMemory`，同 `SummarizeResp.episode_memory` 的做法）。Req 装：`run_id`、`run_goal`、`goals`（目标表最终定案：状态、`note`、`overturned`）、`episode_memories`（本 run 全部局）、`termination`、`judge_reason`、`episodes`（= `RunResp.total`）、`succeeded`、`acts_used`（= 各局 `EpisodeOutput.acts_used` 之和；`RunResp` 没有这个字段，由新格自己求和）、`max_episodes`。
- **成败标注**：每局的成败以**目标表的最终定案**为准（含人审推翻），不再多问一次校验模型——与 episode 层不同，run 层没有 `verify` 这一环，不新增。
- **门面**：`direct/brain_tool.py` 新增 `RunSummarizer`；`direct/interface/ports.py` 新增 `RunSummarizePort`；`BrainTool.build()` 产出并经 `build.py` 注入 `RunRuntime`（依赖注入，装配点仍只递裸字段）。provider 槽位复用 `summarize` 那一档，不新增 `BrainTool.build()` 参数。
- **prompt**：`direct/prompts/calls/summarize_run.md` + `direct/prompts/summarize_run.py`（`build_prompt`），结构仿 `summarize.md`；既有 `summarize.md` / `summarize_task.md` 不动。
- **收尾位置**（v1.3 对 `run_graph.py` 核实后改）：`run_done` 有两条入边——`review_and_judge` 判停、`plan_run` 之后已 `done`——两条条件边的目标都改为新格 `summarize_run`，其后 `summarize_run → store_run_memory → run_done → END`。`run_done`（记 `run_end`，`settle_run()` 不变）仍是终止唯一出口，`run_end` 仍是 run 的最后一条账；新格运行时 `state.done` 与 `termination` 已定，`RunState` 不变。`summarize_run` 问模型并记账；`store_run_memory` 先查 `run_id` 再写，已有记录一字不动。`run_graph.py` 的模块 docstring（『6 格 + 1 条条件边』）随之更新。
- **失败降级**：蒸馏耗尽重试（`MaxRetriesExceeded`）、预算耗尽（`BudgetExhausted`）、没有 EpisodeMemory——都**不上抛**，落空章，并记 `call_exhausted`。理由：run 已经结束，上抛会丢掉 `RunResp`；这与 episode 层的「耗尽即上抛」不同（Q7 已确认）。
- **图**：素材带各局首末帧，过 `SCOPE_IMAGE_CAP`（D9）（Q2 已确认带图）。
- **收尾路径核实（v1.3）**：正常终止只有 `run_done` 一个出口（`run_graph.py` 唯一通向 END 的边）；`run_entry.close()` 只做结算与账聚合，不是终止出口；`checkpoint.restore` 续跑进同一张图，同样经过新格。异常路径（`new_run` 的 `except` 记 `run_error` 后原样上抛）**不写 RunMemory**：run 没有可信的终态，且从存档续跑到收尾时由新格补写（先查 `run_id` 再写保证不重复）。这把 intent 的『含异常收尾』收窄为『正常收尾』，intent 已同步，见 Q10。执行方发现图外另有终止路径则停下汇报（停止条件）。

### D6 记忆存储与召回口

- 新 kind：对外 `run`，存储目录 `run_memory`，**md 类**（frontmatter + 正文，与 episode 同）。改动点（v1.3 对 `ce1e9c3` 逐项重核）：`memory/recall.py::_KIND_DIRS` 加 `"run": "run_memory"`（`MemoryCapability` 的 store 表由它生成，自动成为六族）；`memory/store.py` 的 `_MD_KINDS` 加 `run_memory`（`_KINDS` 随之含它；`restore` 的『不安全条目 / 未知目录』校验与清库循环都读 `_KINDS`，所以空 zip 还原会连 run 记忆一起清空，评测的 `evals/common/memory_server.py::clear_memory` 不用改，只加测试钉住）；`MemoryCapability.memorize()` 加 `elif kind == "run"` 与 `_memorize_run`；`MemoryCapability.restore()` 末尾重读循环 `("task", "episode", "object", "knowledge")` 加 `"run"`（漏列会让还原后读不到 run 记忆）；两处 Literal 加 `"run"`——`FromHarnessToMemoryToolMemorizeRecord.kind` 与 `FromHarnessToMemoryToolRecallItem.kind`（后者 v1.2 漏列）；`mcp_servers/memory_server.py` 的 `memorize` 工具说明里的 kind 清单；注释里的『五族 / 五类』改『六族 / 六类』（`memory/recall.py`、`mcpclient/memory_local.py`、`docs/spec/memory/SPEC.md`）。`docs/mcp/memory-admin-spec.md` 里没有 kind 清单，MCP 服务端没有按 kind 分的工具，核对后都不改。
- 元数据：`{"run_id", "run_goal"}`。
- **召回新取法 1**：`conditions={"run_goal": X}` → episode 族按 `run_goal` 等值筛选（`_recall_episode_summaries` 的条件键白名单 `("run_id", "episode_id")` 加 `run_goal`；触发分族的 `if run_id or episode_id or query` 加上 `run_goal`）。排序：按 `(run_id 自然序, episode_id 自然序)`，使跨 run 的顺序稳定。`run_goal` 是任意文本（含中文、空格、竖线），元数据等值筛选对取值没有限制，CP1 用测试钉住。`recall()` 末尾的 `items[:limit]` 会截断（默认 8），调用方沿用现有两处调用的约定 `limit=10**6`。
- **召回新取法 2**（v1.3 改 hint 名）：`conditions={"runs": "all"}` → 只返回 run 记忆族，全部，按 `run_id` 自然序，item 的 kind 为 `run`。v1.2 写的 `{"kind": "run"}` 与 `FromHarnessToMemoryToolRecallReq` 的约定冲突（该信封规定 conditions『不放 kind』：按 hint 分族圈定是底层规则，不是调用方的选择），故改用上下文 hint `runs`；信封的 `conditions` 说明与 `recall()` docstring 的分族规则同步补这一条。`runs` 不与其他键组合。
- 不新增任何 `MemoryStorePort` 方法：两种取法都落在既有的 `filter()` 上。
- **无条数上限**：episode 局摘要的数量上限（`max_summaries`）与淘汰（`_trim_episodes`）已由 CHANGELOG 478 删除，episode 记忆只增不淘汰，L1 的跨 run 索引不会因淘汰缺局。run 记忆同样不设条数上限；本项目不重新引入任何淘汰。

### D7 三层的数据取法（perceive 单元的改动）

- **run 层** `read_plan_context`：①`recall(conditions={"run_id": 本 run})` 照旧取本 run 全部局，直接作 `details`（删 `_pick_details`）；②新增 `recall(conditions={"runs":"all"}, limit=10**6)`，去掉本 run，得 `run_index`；③`objects` 照旧；④新增知识检索单元（见 D10）。账：`read_episode_memory` 照旧，新增 `read_run_memory`。
- **episode 层** `retrieve_global_episode_memory`（改名为 `retrieve_episode_index`）：`recall(conditions={"run_goal": ep 的 run_goal}, limit=10**6)`，去掉本局 `episode_id`，写 `ep_ctx.episode_index`。`retrieve_task_memories` 不变。账：复用 `read_episode_memory`，`query` 字段写 `run_goal=…`。
- **task 层**：不新增召回。`dispatch_task` 从 `ep_ctx.task_memories` 中取**目标文本与当前 task 的 `goal` 相等**的此前 task，去掉首末帧后放进 `TaskInput.task_index`（新字段），task 图把它抄进 `task_ctx`。`retrieve_act_memories` 已是「本 task 全部」，不变；`plan_task` 与 `review_and_judge` 去掉切片。
- **「此前的 task」**：本 episode 内已有 TaskMemory、且 `goal` 与当前 task 相同的 task（同一个 task 目标被重新发起，典型场景是上一版任务链失败后 `plan_episode` 重拆出同目标的 task）。没产出 ActMemory 的 task 没有记忆，不在其内。上限是本 episode，不跨 episode。按 `total_acts` 升序。
- **匹配口径**：`goal` 文本逐字相等。模型重拆时若改写了目标文字，这条索引就是空的——这是已知限制，不做模糊匹配（模糊匹配要调模型或语义检索，违背「索引机械生成」）。

### D8 删窗口

- `CHOOSE_HISTORY_STEPS`、`JUDGE_HISTORY_STEPS` 删除；读方各一处（`plan_task/__init__.py:45`、task 层 `review_and_judge/__init__.py:49`）改为取全部。
- 上限靠既有预算：task 层 `min(Task.max_steps, task_max_steps=12)`（`task_entry.py:63`，硬）；episode 层 `min(goal.max_steps, episode_max_tasks=6)`（硬；`EPISODE_MAX_TASKS_PER_PLAN=5` 只是给模型的建议，不截断）；run 层 `max_episodes`（D11）。
- 一个 task 内一轮至多一条 ActMemory（`act` 一轮落一个键或一个脚本，脚本也只落一条带结果行的记忆），所以 task 层详情至多 12 条，去重后至多 13 张图。执行方须用测试确认「一轮一条」，不成立则停下（停止条件）。

### D9 图

- `BrainPort.plan` 与 `decompose` 各加 `images: Sequence[str] = ()`，形状与 `judge` / `choose` 一致（brain 对外接口变化，Q 列表）。`Planner` / `Decomposer` 把 req 里的帧拼成 `images` 传下去。
- 来源：L0 = `details` 每局 `first_frame` / `last_frame`；L1 = `task_memories` 每条 `first_frame` / `last_frame`；L2 = `dedup_snapshots(memories)`（不变）；run 蒸馏 = 各局首末帧。
- 去重：按帧字符串相等（同 `dedup_snapshots` 的做法）；缺帧跳过。
- **共用上限**：`config.py` 新增 `SCOPE_IMAGE_CAP = 20`（实验旋钮），工具函数 `cap_images(frames, cap)` 住 `direct/brain_tool.py`，保留**最新**的 `cap` 张、从最旧的丢。L0 / L1 / run 蒸馏过帽；L2 不过帽，因为它的帧与 `$memories` 文字逐帧对应（丢帧会错位），其上界是 `task_max_steps + 1 = 13`。装配期断言 `SCOPE_IMAGE_CAP >= task_max_steps + 1`（`build.py`），防止预算被调大后 L2 超帽。
- 取值依据：L0 最多 `2 × max_episodes = 20`；L1 最多 `2 × episode_max_tasks = 12`；L2 最多 13。20 恰好容下 L0 的全部帧。

### D10 知识与 RAM 现状六处都给

- **RAM 现状**：L0 = `RunState.observation`（run 层 `perceive` 已取帧）；L1 = `ep_ctx.observation`（`plan·L1` 已有，补给 `judge·L1`）；L2 = 已有（`plan·L2` 的 `obs`，`judge·L2` 的 `$observation`）。
- **知识**：L1、L2 已有（`ep_ctx` 检索，经 `TaskInput.knowledge` 到 task 层）；补给 `judge·L1` 与 `judge·L2`（复用同一份，不再检索）。**run 层目前没有知识检索**，新增 `retrieve_knowledge_semantic_memory` 的 run 级单元：query 用 `build_knowledge_query(RunState.observation, run_goal.goal)`，条数 `MEMORY_RECALL_LIMIT`，账复用 `read_knowledge`；每个 run 开局与每圈 `plan_run` 前取一次（与 episode 层「首圈、场景变了、有失败」的重查规则不同，run 层圈数少，简化为每圈取），结果写进 `PlanContext.knowledge`。
- 判定员三处的 prompt 模板各增 `$knowledge`（与决策侧同样的可信度说明），`$observation` 已有者不增。

### D11 预算

- `DEFAULT_RUN_BUDGET.max_episodes` 50 → 10（`config.py:144`）。评测对它的覆盖不变。
- 需同步改：`tests/budget/test_run_config.py:21`（断言 50）、`docs/budget/run-budget-spec.md` 的 D1 与 D11 两行（『生产值恢复 50』『生产：…`max_episodes=50`…』，v1.3 核实）、`docs/spec/build/SPEC.md:105` 附近引用窗口常量的句子。
- 取值依据：L0 详情 ≈ `max_episodes × 一条 EpisodeMemory 渲染长度`；仓库内没有真实运行产出的记忆样本，无法在 spec 阶段测长度。取 10 是用户给的 8–12 的中位偏上；真实长度出来后复核（遗留项）。

### D12 死代码清理（随引起它的检查点同提交；先查读方，读方清零才删）

| 项 | 读方 / 位置 | 随哪个检查点 |
|---|---|---|
| `CHOOSE_HISTORY_STEPS`、`JUDGE_HISTORY_STEPS` | `config.py:222,228`；两处读方；注释 `judge_success.py:74`、`act_memory.py:324`；`docs/spec/build/SPEC.md:105` | CP3 |
| `_pick_details`（最近 1 局 + 失败局） | `run/perceive/read_plan_context.py` | CP6 |
| `PlanOnceReq.index` 与 `run_plan.py::index_lines`（旧一行/局渲染）的旧语义 | `direct/prompts/run_plan.py` | CP6 |
| `ChooseOnceReq.episode_memories: str` 与 `$episode_memories` 占位符 | `decide_action.py:219,254`、`decide_action.md` | CP3 |
| `DecomposeReq.episode_memories`（旧语义，改名 `episode_index`） | `plan_episode._request`、`decompose.py:47-48` | CP5 |
| `ep_ctx.global_episode_memories` | `retrieve_global_episode_memory` 与读方 | CP5 |
| 历史记录（`CHANGELOG.md`、`changelog/`） | **不改** | — |

### D13 状态模型、哈希与评测存档

- `state_schema_hash` 是 `RunState` / `EpisodeRunState` / `TaskState` 三个模型 JSON Schema 的哈希，嵌套模型加字段即变。探针：仅给 `EpisodeMemory` 加首末帧即 `4f1cac6fcc7216d5 → 9cdad311e4226c69`。本项目会多次改变它（`EpisodeMemory`、`PlanContext`、`ep_ctx`、`EpisodeInput`、`TaskInput`）。
- **基线哈希（v1.3）**：`4f1cac6fcc7216d5` 是 `352af88` 时的实测值；MCP-only 没有改三个状态模型，预计不变，但 v1.3 未复测。CP1 起点（改动前）由执行方在项目 venv 实测并汇报，之后的『实测哈希』以它为参照。
- 每个检查点完工时执行方汇报实测哈希；中间态的存档不可加载（评测是真实模型运行，不在 CI 内），**存档只在最后一个检查点重打一次**。
- 重打命令（remove-vision 用过）：`python -m evals.agent_short_goal_run.dataset.build.pack`（20 份 v1 存档，`world.state` 的 sha256 必须逐项不变，不再被引用的旧记忆快照 zip 用 `git rm` 删除）。该命令可能需要 ROM / 模拟器，由用户在本机执行并确认；执行方不跑。CP8 同时由用户清空本机开发用记忆库里没有 `run_goal` 的旧 episode（Q8：直接删，不做兼容、不回填）；清空可用管理面空 zip 还原，评测的 `clear_memory` 就是这个做法。

### D14 与 reviewer 的衔接

- reviewer 分支（`feature/reviewer-transparency`，R3 待执行）的 `ReviewContext.brain_input` 为 `PlanOnceReq | DecomposeReq | JudgeReq`，渲染时跳过 `plan` / `task_table`。本项目保留这三个字段，改的是素材字段（见第一节），所以 `render_context` 的跳过规则不受影响，但它渲染 `brain_input` 的其余字段要适配新字段名。
- 其 spec 更正 #18「规划与拆解处大脑不看图」与本项目冲突：图经 `details` / `task_memories` 里的首末帧字段进入 req，**渲染文本必须不输出这些 data URI**（`TaskMemory.render()` 已不输出帧，EpisodeMemory 同）。
- **合并顺序**：建议本项目先合入，reviewer R3 在新请求形状上落地。编号：reviewer 原占的 460–462 与主线已冲突（主线已用到 483），等它恢复时由设计侧统一重编号。

### D15 trace：新增三本账（Q1 已确认）

铁律 6「每一步都必须产出 trace 事件」；新增的执行路径需要账：

| kind | type | 谁发 | 内容 |
|---|---|---|---|
| `summarize_run_call` | `model_call` | `summarize_run` | 蒸馏调用整条账（同 `summarize_episode_call`） |
| `read_run_memory` | `memory_io` | `read_plan_context` | 读到的 run 记忆的 `run_id` 清单 |
| `write_run_memory` | `memory_io` | `store_run_memory` | 落库的 run 记忆（含空章标志位的反函数见 `write_episode_memory` 的做法） |

其余读写复用既有 kind（L1 索引复用 `read_episode_memory`；run 层知识复用 `read_knowledge`）。需同步：`schemas/harness/domain/trace_kind.py`、`direct/trace/content.py` 与 `render.py`、`docs/spec/DATAFLOW.md` 事件总表。落点已由用户确认（Q1）。

### D16 测试范围

用户确认：单元测试 + 一个 FakeLLM 范围一致性集成测试（验收 1）。不连网、不调真实模型、不依赖时间戳精确值。

---

## 三、检查点（一个检查点一次验收、一个提交；顺序执行，同一分支）

| CP | 内容 | 完工判据（执行方汇报前） | 我的核对点 |
|---|---|---|---|
| CP1 | **基建与记忆侧**：`pyproject.toml` 的 ruff `extend-exclude` 补 `.worktrees`；`EpisodeMemory` 三字段；`RunMemory` 模型；三个 `index_line()` 与首句规则；kind `run` 的存储 / 召回 / memorize 分发 / restore / 两处 Literal / MCP 说明 / 文档；两种召回新取法（`run_goal` 与 `runs` hint）；起点先在项目 venv 实测并汇报基线哈希 | 新增单元测试全绿；旧 payload 缺字段可读；`restore` 后 run 记忆可读；报实测哈希 | 读 `recall.py` / `store.py` diff；破坏验证（把 `restore` 重读循环里的 `run` 去掉，对应用例应失败） |
| CP2 | **写入侧**：`EpisodeInput.run_goal` 传递；Summarizer 与空章盖 `run_goal` 与首末帧；run 蒸馏链路（`BrainPort.summarize_run`、信封、`RunSummarizer`、端口、prompt、`summarize_run` / `store_run_memory` 两个新格与 `run_graph.py` 两条条件边、降级）；三本账 | 单元测试 + 一个「`store_run_memory` 重复调用只落一条」的测试 + 一个「所有指向 `run_done` 的边都先经新格」的测试全绿 | 读 `run_done` / `run_entry` 路径；prompt 文本；账的 `meta` 契约 |
| CP3 | **L2**：`plan_task` 与 task 层 `review_and_judge` 取全部；`TaskInput.task_index` 与 `dispatch_task`；`ChooseOnceReq` / `JudgeReq` 字段与渲染；`judge·L2` 的 `$knowledge`；删两个窗口常量与 `episode_memories: str`；`SCOPE_IMAGE_CAP`、`cap_images`、装配期断言 | 全量测试通过；`grep` 两个常量零残留（历史记录除外） | 读两处切片删除的 diff；L2 的图与 `$memories` 仍逐帧对应 |
| CP4 | **图通道**：`BrainPort.plan` / `decompose` 加 `images`，`Planner` / `Decomposer` 拼图；brain 的 mock 与实现同步 | 铁律 4（mock 与真实同一 Protocol）；测试全绿 | 读 `brain_port.py` 契约 docstring |
| CP5 | **L1**：`retrieve_episode_index`；`DecomposeReq.episode_index`、`JudgeReq` 增字段；`plan·L1` / `judge·L1` 的渲染与 `$knowledge`；L1 带图；删 `global_episode_memories` | 测试全绿 | 读召回条件；「不含本局、只含同 `run_goal`」的用例 |
| CP6 | **L0**：`read_plan_context` 改为详情全部 + `run_index`；run 层知识检索单元；`PlanOnceReq` / `JudgeReq` 改字段与渲染；L0 带图；删 `_pick_details` 与 `index` | 测试全绿 | 读 `run_plan.md` / `run_plan.py` 的 diff；run 层 prompt |
| CP7 | **预算与集成**：`max_episodes` 10 及其测试与文档；FakeLLM 范围一致性集成测试；残留扫描；DATAFLOW / SPEC 文档同步 | 全量 pytest、`ruff check`、`ruff format --check` 全绿 | 集成测试断言的是验收 1、2、4；文档与代码相符 |
| CP8 | **存档重打（用户）**：记录最终 `state_schema_hash`；用户在本机跑 `pack`，核对 `world.state` sha256 不变 | 用户确认 | 设计侧只核对结果 |

每个检查点的「允许改动的文件」与 CHANGELOG 编号在 plan 里列。CP1–CP7 依次占 485–491（478–483 已用，484 预留给测试瘦身 `chore/test-reclass`），派发时逐个先登记台账再发交接。

---

## 四、文件改动清单（总览，按目录；精确到检查点的清单在 plan）

- `pyproject.toml`：ruff `extend-exclude` 加 `.worktrees`。
- `pokemon_agent/config.py`：删两个常量；`max_episodes=10`；加 `SCOPE_IMAGE_CAP`。
- `pokemon_agent/schemas/memory/datastore/`：`episode_memory.py`（三字段、`index_line`）、`task_memory.py`（`index_line`）、新增 `run_memory.py`、统一出口。
- `pokemon_agent/memory/`：`recall.py`、`store.py`；`mcp_servers/memory_server.py`（工具说明）；`mcpclient/memory_local.py`（docstring）；`docs/spec/memory/SPEC.md`（『五类』→『六类』）。`docs/mcp/` 管理面契约核对后不改。
- `pokemon_agent/schemas/harness/`：`communication/` 下 `PlanOnceReq`、`DecomposeReq`、`ChooseOnceReq`、`JudgeReq`、`MemoryToolMemorizeReq`、`MemoryToolRecallReq`（说明）、`MemoryToolRecallResp`（Literal），新增 `SummarizeRunReq` / `Resp`；`domain/` 下 `episode_io.py`、`task_io.py`、`trace_kind.py`。
- `pokemon_agent/brain/interface/`：`brain_port.py`（`summarize_run`；`plan` / `decompose` 加 `images`）、`domain/` 新增 `run_summary.py`；`brain/brain.py`、`providers.py`（接线）。
- `pokemon_agent/direct/`：`brain_tool.py`（`RunSummarizer`、`cap_images`、`Planner` / `Decomposer` 拼图）、`interface/ports.py`、`prompts/`（`run_plan`、`decompose`、`judge_success`、`decide_action`、新增 `summarize_run` 及 `calls/summarize_run.md`、各 `.md` 模板）、`trace/`（`content.py`、`render.py`）。
- `pokemon_agent/harness/`：`run/perceive/read_plan_context.py`、新增 run 层知识单元、`run/run_state.py`（`PlanContext`）、`run/run_graph.py`、新增 `run/summarize_run` 与 `run/store_run_memory`、`run/act/dispatch.py`、`run/runtime.py`（`run/run_done` 不改）；`episode/perceive/retrieve_global_episode_memory.py`（改名）、`episode/episode_state.py`、`episode/plan_episode`、`episode/review_and_judge`、`episode/act/dispatch_task.py`、`episode/episode_done/`（盖章）；`task/plan_task`、`task/review_and_judge`、`task/task_state.py`、`task/task_entry.py`。
- `pokemon_agent/build.py`：注入 `RunSummarizePort`；装配期断言。
- `tests/`：随各检查点（第五节）。
- `docs/`：`docs/spec/build/SPEC.md`、`docs/budget/run-budget-spec.md`、`docs/spec/DATAFLOW.md`、`docs/mcp/*`；`CHANGELOG.md` 逐检查点追加。

不改：蒸馏 prompt（task / episode）、世界层、`review_backend`、`agent_reviewer`、`CLAUDE.md` / `AGENTS.md`。

---

## 五、测试清单

**单元（每条一句话命名）**

- `test_episode_index_line_matches_fixed_sample` / `test_task_index_line_matches_fixed_sample` / `test_run_index_line_matches_fixed_sample`
- `test_first_sentence_stops_at_terminator_and_truncates_at_eighty_chars` / `test_empty_summary_index_line_says_no_body`
- `test_episode_memory_reads_old_payload_without_new_fields`
- `test_run_memory_round_trips_through_memorize_and_recall`
- `test_recall_by_run_goal_returns_only_matching_episodes_across_runs`
- `test_recall_runs_hint_lists_every_run_memory_and_no_episode`
- `test_run_goal_with_spaces_and_cjk_matches_by_equality`
- `test_restore_reloads_the_run_memory_family`
- `test_restore_with_an_empty_archive_clears_run_memory`
- `test_episode_chapter_carries_run_goal_and_first_last_frames` / `test_empty_chapter_carries_run_goal_and_no_frames`
- `test_store_run_memory_writes_once_even_when_called_twice`
- `test_every_edge_into_run_done_goes_through_the_run_summary_cells`
- `test_run_summary_failure_degrades_to_an_empty_chapter`
- `test_one_round_produces_one_act_memory_even_for_scripts`
- `test_plan_task_and_task_judge_read_all_act_memories`
- `test_task_index_lists_prior_tasks_with_the_same_goal_in_this_episode_only`
- `test_episode_index_excludes_current_episode_and_other_run_goals`
- `test_run_index_excludes_current_run_and_ignores_run_goal`
- `test_run_plan_details_are_all_episodes_of_this_run`
- `test_cap_images_keeps_newest_and_drops_oldest`
- `test_plan_and_decompose_pass_images_to_the_brain`
- `test_assembly_rejects_image_cap_below_task_steps_plus_one`
- `test_default_budget_max_episodes_is_ten`

**集成（项目的使用说明书之一）**

- `test_three_levels_plan_and_judge_read_the_same_details`：FakeLLM + 假记忆，装好三层的请求，断言 ①同层 plan 与 judge 的详情是同一份、条数等于绑定单元下全部子记忆；②索引不含本单元；③索引生成过程零模型调用（FakeLLM 计数）。

**需随改动调整的既有测试**（执行方按 grep 找全）：`tests/budget/test_run_config.py`；引用 `DecomposeReq` / `PlanOnceReq` / `ChooseOnceReq` / `JudgeReq` / `dedup_snapshots` 的 `tests/direct/prompts/test_decide_action_prompt.py`、`tests/harness/perceive/test_memory_observation.py`、`tests/integration/test_p5_script_actions.py`、`tests/budget/test_budget_settlement.py`、`tests/budget/test_deadline.py`；`evals/brain_goal_judge/dataset.py` 若构造旧形状的 `JudgeReq`。

---

## 六、验证方式

- 全部自动测试不连网、不调真实模型、不用模拟器。每个检查点汇报前：全量 `pytest`、`ruff check`、`ruff format --check` 全绿；破坏验证按核对点做。
- 真实运行：本项目**不需要**。CP8 的 `pack` 由用户在本机执行；之后用户可自行跑 `agent_short_goal_run` 观察效果（费用由用户确认，非验收条件）。
- 每个检查点汇报实测 `state_schema_hash`。

## 七、停止条件（执行方遇到即停，不重试、不绕过）

- 改动超出该检查点「允许改动的文件」；`HEAD` 或关键哈希与交接消息不一致；起点不是全绿。
- 任何真实模型调用或模拟器调用。
- 需要执行被禁止的 git 命令才能继续。
- 发现存在不经 `run_done` 的 run 收尾路径，或「一轮一条 ActMemory」不成立。
- 召回口改动需要新增 `MemoryStorePort` 方法才能实现。
- 状态哈希变化超出 D13 列出的原因。
- 需要改 `CLAUDE.md` / `AGENTS.md`，或引入第三方依赖。

## 八、非目标

大脑 agent 化与工具式查询（E8）；函数改名；重新生成 level0 目标的机制；既有 task / episode 蒸馏 prompt 与既有 trace 落点；为省 token 折叠记忆正文；重新引入 episode / run 记忆的条数上限或淘汰（上限已由 CHANGELOG 478 删除）；回填旧 episode 的 `run_goal`。

---

## 九、已知观察（探针与读码得到的事实，不钉成测试预期）

1. 基线哈希 `4f1cac6fcc7216d5`；加 `EpisodeMemory.first_frame` / `last_frame` 后 `9cdad311e4226c69`（隔离环境 Python 3.11，复制自 `479d0dd` 的 `git archive`）。v1.3 未在 `ce1e9c3` 上复测（沙箱 Python 3.10、无 pydantic），见头部。
2. 旧 `EpisodeMemory` payload（无新字段）可读，新字段取默认值；`model_config` 为空，多余字段被忽略。
3. 召回口的 episode 族只认 `run_id` / `episode_id` 做等值键；episode 元数据现为 `run_id`、`episode_id`、`success`、`quality_score`、`scene`；`run_goal` 只存在于 trace 与存档清单。
4. episode 局摘要的条数上限与 `_trim_episodes` 已于 CHANGELOG 478 删除（D6）；主线上已不存在。
5. 运行时上限：`task_entry.py:63` 的 `min(task.max_steps, 12)`；`EPISODE_MAX_TASKS_PER_PLAN` 不截断；episode 硬上限 `min(goal.max_steps, 6)`。
6. 现状里 `ChooseOnceReq.episode_memories` 无写方，是已有陈旧项。
7. `ReviewContext` 与本项目互不依赖，但共用请求类型（D14）。
8. 记忆根的 `restore` 在清单外逐族重读（D6），新增 kind 容易漏。
9. 创建 worktree 时 git 在连接文件夹里无法删除自己的 `.lock`，已改名挪开；后续提交同样会留锁，处理办法见起点说明。
10. `recall()` 末尾 `items[:limit]` 截断，默认 limit=8；现有两处 episode 召回都传 `10**6`（v1.3）。
11. `RunResp` 的字段是 `run_id / outcomes / total / succeeded / success_rate / termination / judge_reason`，没有 `episodes`、`acts_used`（v1.3）。
12. `run_graph.py` 里 `run_done` 有两条入边（`review_and_judge`、`plan_run` 之后），`run_entry.close()` 只结算；异常上抛不经 `run_done`（v1.3）。
13. `FromHarnessToMemoryToolRecallItem.kind` 与 `...MemorizeRecord.kind` 是两份独立的 Literal，v1.2 只列了后者（v1.3）。

## 十、修正表（与 intent / 起点说明不一致或需补充处）

| # | 内容 | 处理 |
|---|---|---|
| 1 | 起点说明原写「EpisodeMemory 不在状态哈希内（预计）」 | 实测在内（嵌在 `PlanContext` / `ep_ctx`），哈希会变，已纳入 D13 |
| 2 | 起点说明原写 `GoalEntry` 只有 `last_episode_id`，需决定按 id 还是文本过滤 | 定为：L1 按 `run_goal` 等值，不按 goal id；L2 不跨 episode |
| 3 | intent 验收 5「仓库内零残留」 | 已在 intent 中限定为代码、测试与现行文档，历史记录除外 |
| 4 | `PlanOnceReq.index` 删除（intent 未提） | D1 / 1.1：详情已含全部局，两处传违背「同一东西绝不两处传」 |
| 5 | `judge·L2` 不新增 `observation`（v1.1 注：L2 索引口径已改，见第 11 行） | 已有 `$observation`，由全部 `history` 的最后一条 `after` 渲染 |
| 6 | **L1 行为变化**：decompose 原本看到本 run 全部局的全文，现在只看 `run_goal` 相同的局的一行索引 | 来自 intent 的范围规则，需用户再确认（Q4） |
| 7 | intent 原写「trace 落点不动」 | 已改为新增三本账（D15），需用户确认（Q1） |
| 8 | run 级记忆原默认机械来源章 | 已改为蒸馏（D4 / D5），按用户要求 |
| 9 | 图在 L0 / L1 的进入方式 | 经 req 内的首末帧字段，不在信封里另开通道（与既有「图随记忆」一致） |
| 10 | `ChooseOnceReq.episode_memories` 陈旧项 | 随 CP3 清理 |
| 11 | v1.0 把 L1 写成「含本 run 其他局与过往 run 的局」，把 L2 写成「本 episode 内全部此前 task」 | v1.1 改正：L1 的集合就是 `run_goal` 相等的 episode（run 内所有局共享同一 `run_goal`，所以本 run 的其他局自然在内；过往 run 在内只因同一目标被重新发起）；L2 只含**目标文本相同**的此前 task |
| 12 | **v1.2**：`max_summaries` 与 `_trim_episodes` 已删除（CHANGELOG 478） | D4 / D6 / 第八、九节 / Q5 随之更正；编号从 480 起（479 被 mcp-only 批 ① 占用）；基线改为 `352af88` |
| 13 | **v1.3**：基线前移到 `ce1e9c3`，记忆侧对新代码重核 | 见头部修订原因。另：①intent 里『按 `episode_goal` 取 task』『含异常收尾』与 spec 不一致，intent 已改成最终版；②『列出 run 级记忆』的 hint 由 `kind` 改 `runs`；③run 蒸馏改为 `run_done` 之前的两个新格；④异常上抛的 run 不写 RunMemory（Q10） |

## 十一、用户确认记录

> 2026-10-17：Q1–Q9 全部按设计侧推荐确认；Q8 经用户补充改为『旧 episode 直接删除』。

- **Q1** trace 新增三本账（D15）：`summarize_run_call` / `read_run_memory` / `write_run_memory`，可以吗？
- **Q2** run 蒸馏是否带各局首末帧？默认带（过 `SCOPE_IMAGE_CAP`）；不带则省 token，`summarize_run` 不收 `images`。
- **Q3** `SCOPE_IMAGE_CAP = 20` 与「L2 不过帽」可以吗？
- **Q4** L1 行为变化（修正表 6）可以接受吗？即 decompose 不再看到同 run 内其他 `run_goal` 目标的局的全文，也不再看本 run 全部局的全文，只看 `run_goal` 相同的局的一行索引。
- **Q5** ~~`max_summaries` 全局淘汰~~：已消解（CHANGELOG 478 删除了上限与淘汰）；run 记忆也不设条数上限，无需再确认。
- **Q6** 合并顺序：本项目先合入，reviewer R3 随后适配。可以吗？
- **Q7** run 蒸馏失败时降级为空章、不上抛（与 episode 层不同）。可以吗？
- **Q8**（已确认，口径改为）旧 episode 直接删除，不做兼容、不回填；清空放在 CP8。
- **Q9** `BrainPort` 新增 `summarize_run`、`plan` / `decompose` 加 `images`——这是 brain 模块对外接口的变化，可以吗？
- **Q10**（v1.3 新增，设计侧按默认执行，请知悉）异常上抛的 run 不写 RunMemory，从存档续跑到收尾时才写；intent 的『含异常收尾』已收窄为『正常收尾』。如果要求异常也落空章，CP2 要多改 `new_run` 与 `checkpoint.restore` 两处 `except`，告诉我即可。
