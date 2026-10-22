# CP6 细化（草案，待用户确认 6 个决定）

> 依据：spec.md 第五节 CP6、夜间总汇报第五节、2026-10-22 对分支 HEAD e2ae8a0 的读方清查。
> 原则不变：先加后减。CP6 拆成三步，每步一次验收、一次提交；删除类操作放最后。

## 一、清查结果（生产代码）

**旧渲染方法**，在 prompt 模块之外仍有读方的：

| 方法 | 读方 | CP6 处置 |
|---|---|---|
| `Observation.render()` | `direct/brain_tool.py::_render_observation`（Reflector 拼 `brain.reflect` 的 before/after 文本） | 决定 D |
| `index_line()`（Episode/Run/Task 记忆） | `reviewer/hub/context.py:18` | reviewer 自管一份，见决定 E |
| `ActMemory.render` / `render_sequence`、`Facts.render`、`TerrainMap.render` / `render_neighbors`、`PlaceInWorld.render`、`TakeoverView.*.render`、`ScreenText.render_*`、`ActionEntry.signature` | 其余只被彼此调用，或被 `world/task_perception.py` 用来**填旧字符串字段** | 填字段的调用随旧字段一并删；其余整体删 |

**旧字符串字段**：`Facts.where` / `neighbors` / `walk_map`、动态字段 `option_layout` / `option_details`（及 `my_*` / `foe_*`）、`Observation.status`、`TaskObservation.observation_notes`、`ActMemory` 快照里的同名副本。读方：

- `direct/trace/render.py:467` 写 `"status": obs.status`（决定 C）。
- `harness` 的 `knowledge_query` 已在 CP4 去掉 `status`。
- 其余只剩 `world/` 与 `schemas/memory/` 内部。

## 二、清查结果（evals、数据、测试）

- `evals/decode/solver.py:41-44` 生成 `where` / `walk_map` / `neighbors` 文本去与真值比。
- `evals/agent_short_goal_run/scorer/rules/shop.py:39` 读 `option_details` 动态字段。
- `evals/common/legacy_requests/judge_prompt.py` 是冻结的旧 prompt 副本（CP7 处置）。
- 46 个数据文件含这些旧字段名（`brain_calls/v1`、`brain_calls/v2…`、`brain_choose`、`brain_judge`、`frames`）。这些是**冻结真值与历史请求，不改文件**；`Facts` 为 `extra="allow"`，旧键仍可读入，只是不再被消费。
- `choose_review`（`evals/dataset/brain_annotations/choose_review.py`）解析 `walk_map` 文本，需改读 `cells`。
- 测试：引用旧 `.render()` / `index_line` / 旧字段的既有测试，随各步改写。

## 三、三步拆分

### CP6a 切换读方（只加不删，编号 594）

- Reflector：按决定 D 处理；`trace/render.py`：按决定 C 处理；reviewer：按决定 E 自管 `index_line` 等价逻辑。
- `evals/decode/solver.py` 改为比较结构（`place`、`cells`、`neighbors` 字典）；`shop.py` 改读 `ScreenText.option_*` 的结构化字段；`choose_review` 改读 `cells`。
- 此步结束时：旧方法与旧字段**仍在但已无读方**；用脚本核对读方清零（grep 证据入汇报）。
- 允许触及：`pokemon_agent/direct/brain_tool.py`、`direct/trace/render.py`、`reviewer/hub/context.py`、`evals/decode/**`、`evals/agent_short_goal_run/scorer/**`、`evals/dataset/brain_annotations/choose_review.py`，及对应 `tests/**`、`CHANGELOG.md`。

### CP6b 删除旧字段与旧方法（只减不加，编号 595）

- 删除第一节所列全部旧方法与旧字段；`task_perception.py` 只填结构化字段；MCP 序列化与契约同步。
- `ActMemory` 快照副本去旧字段；`test_facts_dual_copy_parity` 改写其意图。
- checkpoint schema 指纹按决定 A 处理（接受新指纹，旧存档拒绝）。
- 测试适配器（`tests/prompt/legacy_adapter.py`）读原始 JSON 文本，不依赖被删字段；golden 对拍经它仍须逐字节一致。
- 允许触及：`pokemon_agent/world/**`、`pokemon_agent/schemas/memory/**`、`pokemon_agent/mcpclient/**`、`docs/mcp/**`、`tests/**`、`CHANGELOG.md`；**不含** `evals/**` 数据文件。

### CP6c 删除旧记忆（编号 596，需用户授权）

- 删哪些目录见决定 F；删前列清单、逐目录核对读方清零，授权后执行。
- 无其他代码改动。

## 四、待你确认的决定

| 编号 | 决定 | 我的建议 |
|---|---|---|
| A | 旧 checkpoint 存档是否继续兼容 | 不兼容。指纹变了就拒绝读，报明确错误；不写迁移层（与「旧记忆直接删」一致） |
| C | trace 里 `"status"` 键 | 改为写结构化的 `scene` / `overlay` / `place`，去掉 `status`；同步 trace 内容往返测试与 Langfuse 映射 |
| D | Reflector 的 before/after 文本（`brain.reflect` 结果实际被丢弃，只做非空断言） | 在 prompt 模块加一个 `kind=task` 的 `observation_text`，包住现有观测片段；Reflector 经网关取文本，不改措辞 |
| E | reviewer 的 `index_line` | reviewer 自管，复制当前逻辑成 reviewer 内的小函数，不依赖 prompt 模块 |
| F | 「旧记忆」范围：`memory/` 下 `step_memory`（231）、`episode_memory`（9）、`task_memory`（1）、`snapshots`（24）、`object_memory`（38）、`knowledge_memory`（14，其中 12 个入库） | 删 `step_memory`、`episode_memory`、`task_memory`、`snapshots`（含旧 ActMemory 文本字段的）；`object_memory` 与 `knowledge_memory` 不是渲染文本载体，保留。你确认后才动 |
| G | 数据集文件是否改写 | 不改。真值与历史请求原样保留，靠 `extra="allow"` 读入 |

## 五、与夜间总汇报「CP6 前七项」的对应与建议

| 总汇报项 | 建议 |
|---|---|
| 1 旧 checkpoint 策略 | 不兼容：旧存档指纹不符即拒绝并报明确错误，不写迁移层（即上表 A） |
| 2 旧记忆与删除授权 | CP6c 删 `step_memory`、`episode_memory`、`task_memory`、`snapshots`；保留 `object_memory`、`knowledge_memory`（即 F）。授权在 CP6c 开工前单独取 |
| 3 `ActionSpace` 旧扩展 | CP6b 把 `extra="allow"` 改回忽略多余键：冻结输入仍能读入，三个文案键被丢弃；`with_prompt_text` 与客户端补文案逻辑删除 |
| 4 素材出口契约（`render_history`、`part="goals"`、同版本 `history` / `goals` 函数） | 保留，写进 spec 的网关契约与 `assembly` Protocol，各配一条用法测试；它们仍只能经网关调用，不算第二个出口 |
| 5 缺失历史语义（25 条 `where` 不可无损恢复） | 维持明确跳过，不补造字段；在 golden 目录加一页说明，写清 158 条一致 + 25 条跳过的口径 |
| 6 旧存档物体文本分支（`object_semantic_memory`、`merge` 旧分支） | 在 CP6b 与旧字段一并删：它们只服务旧存档，A 决定后已无用途 |
| 7 版本与旧包收口 | 八类接管视图与独立 prompt 原料模型保留；`direct/prompts` 整包、四个旧常量、`evals/common/legacy_requests/judge_prompt.py` 与文档同步放 CP7 |

## 六、允许触及范围（并集，不是预判的精确清单）

读方扫描只能给出范围，**精确清单由 CP6a 的第一步产生**：执行方先对第一、二节所列方法与字段做一次机械读方扫描，把「文件 → 读方位置 → 处置」写成表放进 CP6a 汇报，作为 CP6b 删除的依据。允许触及的并集如下，超出即停下汇报。

**CP6a（594）**
- 生产：`pokemon_agent/direct/brain_tool.py`、`pokemon_agent/direct/trace/render.py`、`pokemon_agent/prompt/**`（新增 `observation_text`）、`pokemon_agent/reviewer/hub/context.py`
- evals：`evals/decode/solver.py`、`evals/agent_short_goal_run/scorer/rules/shop.py`、`evals/dataset/brain_annotations/choose_review.py`（以及读方扫描证明仍读旧文本的 `evals/dataset/**` 构建脚本，逐个列出）
- 测试：`tests/direct/trace/test_trace_render.py`、`tests/harness/review/**`、`tests/memory/test_memory_index_lines.py`、`tests/evals/**`、`tests/prompt/**`
- `CHANGELOG.md`

**CP6b（595）**
- 生产：`pokemon_agent/world/**`、`pokemon_agent/schemas/memory/**`、`pokemon_agent/schemas/harness/communication/**`、`pokemon_agent/mcpclient/**`、`pokemon_agent/memory/**`、`pokemon_agent/harness/episode/**`、`pokemon_agent/harness/task/perceive/**`（旧物体文本分支）
- 文档：`docs/mcp/**`
- 测试：`tests/world/**`、`tests/harness/**`、`tests/mcpclient/**`、`tests/memory/**`、`tests/integration/**`、`tests/_harness_fixtures/**`、`tests/prompt/**`
- `CHANGELOG.md`

**CP6c（596）**：仅删除目录，不改代码。

**始终禁止**：`evals/dataset/**` 下任何数据文件、`pokemon_agent/direct/prompts/**`、`tests/prompt/golden/**` 既有文件。

## 七、已确认的决定与修正（2026-10-22 用户答复后）

| 编号 | 结论 |
|---|---|
| A | 不兼容旧 checkpoint：指纹不符即拒绝并报明确错误，不写迁移层 |
| C | trace 的 `status` 键改为结构化的 `scene` / `overlay` / `place`，去掉 `status` |
| D | **删除 brain 侧的 reflect**：删 `Brain.reflect`、`BrainPort.reflect`、`Reflection` 及其导出；`Reflector`（tool 层，`ReflectPort` 的实现）保留，因为 `ActMemory` 由它用结构化观测组装，与 brain 无关。`Reflector` 不再渲染两帧、不再持有 brain 与网关（构造参数随之去掉）；`BrainTool.build` 同步。`ReflectPort`、`FromHarnessToBrainToolReflectReq/Resp` 不变，产出的 `ActMemory` 与现在逐字段一致 |
| E | reviewer 自管：在 reviewer 内写一个小函数复刻当前 `index_line` 的输出，并以现有样本做逐字节等价测试 |
| F | `memory/` 下**只保留 `knowledge_memory`**，其余（`step_memory`、`episode_memory`、`task_memory`、`snapshots`、`object_memory`）CP6c 全删。注意：`object_memory` 是运行中累积的地图物体事实，被 `memory/recall.py`、`store_object_semantic_memory` 等读取；删后物体检索从空开始，程序仍可运行。删除前执行方列清单，你再授权 |
| G | 数据集文件不改（用户未异议，按建议） |
| H（新） | `evals/decode/solver.py` 比对的真值是冻结的**文本**（`where` / `walk_map` / `neighbors`）。真值文件不改，所以不能让 solver 改成比结构。做法：把当前 `TerrainMap.render` / `render_neighbors` / `PlaceInWorld.render` 的逻辑复制进 `evals/decode/` 作为评测自有的「真值文本格式」函数，先用测试证明它与现有 world 方法对全部真值逐字节相等，之后 world 里的才能删 |

**对第二节清查的修正**
- `choose_review` 及 `evals/dataset/brain_*` 构建脚本解析的是冻结数据里的 `walk_map` 文本，而不是调用 world 的 `render`；历史数据没有 `cells`，无法改读结构。**这类脚本不改**。CP6a 的读方扫描只处理「调用 world / memory 旧方法」的代码与「运行期读取旧动态字段」的代码。
- `agent_short_goal_run/scorer/rules/shop.py` 读的是运行期帧里的 `option_details` 动态字段，需要改读新的结构化字段。

## 八、CP6a 停止后的裁决（2026-10-22）

- **C 细化**：`SenseFrameContent` 已经有 `scene`、`place`，`overlay` 在 `facts` 里，三者本来就进 trace，不需要新增 `overlay` 键。所以只做一件事：`render.py` 不再写 `status`；`SenseFrameContent.status` 改为 `str | None = None`（只读兼容，不再写出），这样盘上已有的旧 trace 仍能解析（`_Content` 是 `extra="forbid"`，删字段会让旧账本读不进来）。不改 trace 词表、不改 `ModelCall`。
- **允许范围追加**：`pokemon_agent/direct/trace/content.py`（仅 `SenseFrameContent.status`）、`tests/direct/trace/**`（含 `test_trace_parse.py`，并补一条「带 status 的旧事件仍可解析、新事件不写 status」的测试）、`tests/_harness_fixtures/harness.py`（仅 `Reflector` 装配）。

## 九、CP6a 之后的顺序调整（2026-10-22，用户确认）

读方清查发现：旧 `render` / `index_line` / 旧字符串字段仍被 `pokemon_agent/direct/prompts/**`（旧包）及其对拍测试读取，旧包又被少量生产文件的注释与评测构建脚本引用。旧包不先删，旧方法与旧字段就删不掉。顺序改为：

| 步 | 内容 |
|---|---|
| 595 | 收口旧包：删 `direct/prompts/**`、依赖它的对拍 oracle 测试、`evals/common/legacy_requests/judge_prompt.py`、`evals/dataset/brain_judge/build/audit_candidates.py`（用户确认随旧包一起删，不改数据文件）、`scripts/capture_prompt_golden.py`；守卫改为「旧包不存在」；golden 文件保留为唯一基线 |
| 596 | 删旧字段与旧方法（原 CP6b 内容），范围与原 CP6b 相同 |
| 597 起 | 删旧 memory（只留 `knowledge_memory`，需用户重新授权）；文档同步（`AGENTS.md` / `CLAUDE.md` / `docs/spec`）。编号届时取号 |
