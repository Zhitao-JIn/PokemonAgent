# spec —— prompt 模块（v1.0）

> 依据：`docs/prompt_module/intent.md`（已确认）、`docs/prompt_module/migration-order.md`
> 基线：`main` @ `2c95ab9`（2026-10-21）。本文的事实断言均已对该基线的真实代码核实。
> 流程位置：intent（已确认）→ **spec** → plan（`plan.md`）→ 执行 → 验收 → 合入

---

## 一、已核实的事实（本 spec 的地基）

| # | 事实 | 出处 |
|---|---|---|
| F1 | 调用 prompt 装配的只有 `direct/brain_tool.py` 里的 9 个能力对象（`Planner`/`Decomposer`/`Chooser`/`Judger`/`Reflector`/`Verifier`/`Summarizer`/`TaskSummarizer`/`RunSummarizer`）。`Brain` 只收现成字符串 | `brain_tool.py` 全文；`brain/brain.py` |
| F2 | `build.py` 里 `brain(*links)` 被调用 3 次（run / episode / task 层各一份），每次都是 `BrainTool.build(...)` | `build.py` 步骤 3 |
| F3 | `ModelCall.payload: dict[str, str\|float\|list[str]]` 已经装着 `prompt` 全文；`_adopt()` 原样搬运 payload；trace 渲染也是 `dict(call.payload)` 原样透传。因此版本标识可以直接写进 payload，**不改 `ModelCall` 模型** | `ModelCall.py`；`brain_tool.py::_adopt`；`direct/trace/render.py:314` |
| F4 | `AppConfig` 每个字段对应 `default.json` 一个顶层键，零缺省；新增段要同时改 schema、`default.json` | `settings/schema/app_config.py`、`default.json` |
| F5 | `ActionSpace.descriptions` / `note` / `map_note` 的读方：`direct/prompts/decide_action.py`（3 处）；写方：`mcpclient/action_space.py::with_prompt_text`；测试 4 处（`test_decide_action_prompt`、`test_decide_action_script_entries`、`test_action_space`、`test_world_mcp_contract`）。文案是**客户端在 MCP 返回之后**补的（`world_tool.py` 调 `with_prompt_text`），不是 world server 产出的 | grep 全仓 |
| F6 | 九个调用的请求信封：`ChooseOnce`、`PlanOnce`、`Decompose`、`Judge`、`Verify`、`Summarize`、`SummarizeTask`、`SummarizeRun`（决策重试另用本地 `RetryPromptReq`） | `schemas/harness/communication/` |
| F7 | 记忆对象的 `render` / `index_line` 在检索路径上**无人调用**（`memory/recall.py` 用 `summary` / `markdown` 字段）；非 prompt 的消费方只有 `reviewer/hub/context.py:18`（`index_line`） | grep + 读 `recall.py` |
| F8 | `Facts` 已有结构化的 `landmarks`、`dialog_text`、`options`、`cursor`、`map_id`、`facing`、`screen`；仍是渲染文本的是 `where`、`neighbors`、`walk_map`，以及动态字段 `option_layout` / `option_details` / `my_*` / `foe_*`；另有 `Observation.status`、`TaskObservation.observation_notes` | 读 `facts.py`、`task_perception.py`、`task_observation.py` |
| F9 | `TerrainMap` 已是结构化（`cells`、`map_id`、`player_x/y`、`facing`），`render()` / `render_neighbors()` 在它身上；`ScreenText` 已有 `option_grid` / `cursor_cell` / `option_details`；`BattleStatus` 已是结构化 | 读对应 domain 文件 |
| F10 | `evals/dataset/brain_calls/v1/` 有真实请求记录：`choose` 207、`plan` 26、`decompose` 37、`judge` 289、`summary` 99 条（每行含 `request`）；`verify` 无记录。`memory/step_memory/` 有 231 个真实 `ActMemory` 文件，`episode_memory/` 9 个 | `wc -l` 与 `ls` |
| F11 | 历史请求里的观测只有文本形态（`where` / `walk_map` / `neighbors` 为字符串），没有 CP2 将新增的结构化字段 | F8 推论，CP0 需用真实记录再确认 |
| F12 | 工作区文件是 CRLF、HEAD 是 LF。hash 必须先把行尾归一为 LF 再算，否则同一版本在两处 hash 不同 | 项目既有约定（`docs/workflow.md`） |
| F13 | 当前 CHANGELOG 顶号 583；台账里 `tests/trace-unit` 占用 584–586。本线从 587 起 | `overlap.py`、台账 |

## 二、决定表

| # | 决定 | 取舍 |
|---|---|---|
| D1 | 新模块位置 `pokemon_agent/prompt/`，独立模块，对 `pokemon_agent.*` 依赖为零（标准库 + pydantic） | 与 `brain` 同级。旧包 `direct/prompts/` 到 CP7 才删，期间两者并存，名字不同以免混淆 |
| D2 | 网关接口：`PromptGateway.render(task: str, params: BaseModel) -> RenderedPrompt`。`RenderedPrompt` 含 `text`、`task`、`version`、`hash` | 入参是 Pydantic 模型而不是 dict，遵守「跨层一律模型」；网关校验 `params` 的类型等于该任务声明的契约类 |
| D3 | 目录：`prompt/tasks/<task>/params.py`（任务级契约）与 `prompt/tasks/<task>/<version>/{prompt.md, assemble.py, meta.json}` | 版本目录不是 Python 包，`assemble.py` 由网关按路径加载，避免版本之间的名字冲突 |
| D4 | 入参契约类（纯数据类）由 `pokemon_agent.prompt` 包根统一 re-export，供 `BrainTool` 构造；任何版本的 `assemble.py` 都不可从外部 import | 网关仍是唯一的「渲染」出口；契约类是数据形状，同 `brain` 导出 `Action` / `Goal` 的做法 |
| D5 | 拼装函数签名：`assemble(params: <契约类>, compose: Compose) -> str`。`compose(name, params)` 用来调用 `kind=fragment` 的单元；`kind=task` 只能由外部经网关调用 | 共用片段（读屏幕、人类插话、上一次判定行、目标表/任务表行）经 `compose` 组合，不挂在任何任务名下 |
| D6 | `meta.json` 字段：`task`、`version`、`kind`（task 或 fragment）、`params`（契约类名）、`reason`（本版为什么存在）、`hash` | 元数据只写版本相关信息；当前生效版本只由注册表决定 |
| D7 | hash：对 `prompt.md` 与 `assemble.py` 的字节，**先把 CRLF 归一为 LF**，按文件名排序后拼接算 sha256 | F12；hash 覆盖逻辑文件是因为逻辑改动同样改变输出 |
| D8 | 注册表：纯数据 JSON，`{"tasks": {"<task>": {"active": "<version>"}}}`；默认随包；`AppConfig` 新增 `prompt` 段，`prompt.registry` 为 `null` 时用随包默认，否则取该路径（相对仓库根解析，同 `paths`） | 固定历史版本只需换注册表文件，没有 `version=` 参数 |
| D9 | 网关加载时全量校验：注册的版本目录存在；`meta.hash` 与重算一致；契约类存在；每个 `compose` 引用的 fragment 已注册。任何一项不满足即抛异常 | 与「prompt 缺失不是可以兜底的情况」同一原则 |
| D10 | 接线：`build_real` 把 `app.prompt.registry` 作为裸字段递给 `BrainTool.build(prompt_registry=...)`，后者内部造网关并注入 9 个能力对象；三次 `BrainTool.build` 各造一份（解析成本可忽略，不为此在装配点引入新类） | 保持「build.py 对 brain 零 import」「装配点只递裸字段」 |
| D11 | 版本标识入账：能力对象渲染后，把 `prompt_task`、`prompt_version`、`prompt_hash` 三个字符串写进**每次尝试的** `ModelCall.payload`；不改 `ModelCall` 模型，不改 trace 词表 | F3；`payload` 本来就透传到 trace |
| D12 | `decide_action` 的重试纠正说明单列为任务 `decide_action_retry`（入参 `base_prompt`、`attempt`、`reason`、`raw`） | 它有独立契约和独立调用点；仍沿用「追加、不重渲染」以保住前缀缓存 |
| D13 | 对拍输入：历史请求（F10）加合成用例（verify、summarize_task、summarize_run 以及 `decide_action` 的各分支）加真实 `ActMemory`（F10）。因 F11，历史输入进入新契约需经**文本→字段的一次性适配器**，该适配器只存在于 `tests/`，用「新渲染 = 旧文本」的往返来证明自己 | 无法无损还原的样本不入对拍集，数量如实汇报 |
| D14 | 迁移期第一版**不改任何措辞**；差异即缺陷，不是「顺手优化」 | 措辞调整在 CP7 之后以新版本进行 |
| D15 | 新增段 `prompt` 的键只有 `registry`；不在配置里放版本号 | 版本的真源只有一个：注册表 |

## 三、网关与注册表契约（概要）

```python
class PromptGateway:
    def __init__(self, registry_path: Path | None) -> None: ...
    def render(self, task: str, params: BaseModel) -> RenderedPrompt: ...

class RenderedPrompt(BaseModel):
    text: str
    task: str
    version: str
    hash: str
```

- **前置条件**：`task` 已注册且 `kind == "task"`；`params` 是该任务契约类的实例。违反即 `AssertionError`（调用方的 bug）。
- **后置条件**：`text` 非空；`hash` 等于该版本目录的重算 hash。
- **失败**：注册表或版本目录不一致 → 构造网关时抛 `PromptRegistryError`，不进入 run。
- **`compose`**：只在 `assemble` 内可用，只允许 `kind == "fragment"`。

目录示意：

```
pokemon_agent/prompt/
├── __init__.py            # 只导出 PromptGateway、RenderedPrompt、PromptRegistryError 与各契约类
├── gateway.py  registry.py  meta.py  errors.py
├── registry.json          # 随包默认注册表
└── tasks/
    ├── decide_action/{params.py, v1/{prompt.md, assemble.py, meta.json}}
    ├── decide_action_retry/ ...
    ├── judge_success/ ...        ├── decompose/ ...      ├── run_plan/ ...
    ├── verify/ ...               ├── summarize/ ...      ├── summarize_task/ ...
    ├── summarize_run/ ...
    └── fragments/{read_screen, human_note, last_judge, goal_table, task_table, ...}/
```

## 四、任务与入参契约

契约字段是**原始对象字段**，由 `BrainTool` 从 world / memory / schemas 的对象转换而来；不含任何渲染好的文字。「共用片段」列是该任务经 `compose` 使用的片段。

| 任务 | 来源信封 | 入参字段组 | 共用片段 | 迁入 |
|---|---|---|---|---|
| `verify` | `Verify` | `goal`、`knowledge`、`entries`（ActRecord 或 TaskRecord） | — | CP3 |
| `summarize` | `Summarize` | `goal`、`result` 字段（termination 等）、`entries`（TaskRecord）、`verdicts`、步数预算 | — | CP3 |
| `summarize_task` | `SummarizeTask` | 同上，`entries` 为 ActRecord | — | CP3 |
| `summarize_run` | `SummarizeRun` | `run_goal`、`goals`（GoalRecord）、`episode_memories`（EpisodeRecord）、终止与统计字段 | — | CP3 |
| `judge_success` | `Judge` | `goal`、`knowledge`、`history`（ActRecord）、`goal_table`、`latest_planning`、`task_table`、`task/episode_memories`、三类 `*_index`、`observation`、`allow_interrupt` | `read_screen`、`goal_table`、`task_table`、`judge_interrupt` | CP4 |
| `decompose` | `Decompose` | `goal`、`observation`、`task_memories`、`task_table`、`episode_index`、`knowledge`、`last_judge`、`max_tasks`、`execution_order`、`remaining_planning_rounds`、`human_note`、`terrain_meanings` | `human_note`、`last_judge`、`task_table` | CP4 |
| `run_plan` | `PlanOnce` | `run_goal`、`plan`（GoalRecord）、`details`、`run_index`、`knowledge`、`observation`、`objects`（原始事件）、`last_judge`、`max_push`、`human_note`、预算字段 | `human_note`、`last_judge`、`goal_table` | CP4 |
| `decide_action` | `ChooseOnce` | `goals`、`observation`（含 overlay、`covered_by_script`、takeover 联合、结构化观测字段）、`space`（names、mask、entries）、`memories`、`knowledge`、`task_index`、`last_result`、`human_note`、`max_segments`、`known_objects`（原始事件）、`terrain_meanings` | `read_screen`、`human_note` | CP5 |
| `decide_action_retry` | 本地 `RetryPromptReq` | `base_prompt`、`attempt`、`reason`、`raw` | — | CP5 |

- **观测契约**（`ObservationRecord`）在 CP2 定形，随 CP3 首次被使用，最后在 CP5 补齐 `decide_action` 才用到的字段。它由 world 的 `TaskObservation` 转换而来；转换函数住在 `BrainTool` 一侧（tool 层），不住在 prompt 模块。
- `ActRecord` 等记忆契约是**冗余类对象**：与 `schemas/memory` 同构的最小字段集，互不引用。
- `ActionEntry.description` 与 `ScriptParam.description` 是 world 手写的说明文字，**保持在 world**；它们作为数据字段进入 `space.entries`，由 `decide_action` 的 md 决定怎么排版。

## 五、检查点

每个检查点：做完停下汇报；我验收并提交后才放行下一个；回退用 `git revert`。精确的「允许改动文件」见 `plan.md`（CP0、CP1 精确到文件；后续检查点在各自派发前补）。

### CP0 对拍基线（不改生产代码）

- 新增 `scripts/capture_prompt_golden.py`：按 D13 的三类来源生成对拍集，写入 `tests/prompt/golden/<task>/<case>.req.json`（输入）与 `<case>.prompt.txt`（旧 `build_prompt` 的输出）。
- 历史请求：每个家族按 `case_id` 排序后等距抽样，每任务最多 30 条。先尝试 `model_validate` 为**当前**请求信封；失败的再尝试 `evals/common/legacy_requests/` 里同名旧类；仍失败的跳过并计数。
- 合成用例：`verify`、`summarize_task`、`summarize_run` 各至少 5 条；`decide_action` 覆盖 overlay 三种、`covered_by_script`、各 takeover 视图类、`human_note`、`last_result`、`task_index` 有无、`known_objects` 有无、相邻帧去重命中与未命中；`decide_action_retry` 若干；`judge_success` 三层加 `allow_interrupt`。
- 真实 `ActMemory`：从 `memory/step_memory/` 取 20 个，用于 `verify`、`summarize_task`。
- 新增 `tests/prompt/test_golden_baseline.py`：对每个用例重新调用旧 `build_prompt`，断言与已存的 `.prompt.txt` 逐字节相等（证明基线可复现、旧代码未被动过）。
- 不得调用真实模型；对拍集不得含密钥。
- **核对点**：生产代码 `git diff` 为空；每个任务的有效用例数与跳过数如实汇报；golden 总体积 ≤ 5 MB。

### CP1 骨架

- 新建 `pokemon_agent/prompt/`（网关、注册表、meta、hash、错误类型），随包默认注册表（此时登记零个真实任务，或仅登记测试夹具所需的占位）。
- `settings`：新增 `PromptSection`（唯一键 `registry: str | None`），接入 `AppConfig` 与 `default.json`（默认 `null`）。
- `BrainTool.build(prompt_registry=...)` 内部造网关并注入 9 个能力对象；能力对象暂不使用它。提供统一的「渲染并盖章」辅助，把 D11 的三个键写进每次尝试的 `ModelCall.payload`。`build.py` 递 `app.prompt.registry`。
- 守卫脚本 `scripts/check_prompt_boundary.py`：A 模块对 `pokemon_agent.*` 出边为零；B 模块外对 `pokemon_agent.prompt` 的 import 只允许包根的导出名；C `build.py` 对 prompt 零 import。
- 单元测试用临时目录里的注册表与示范单元：渲染成功；hash 不符、版本缺失、契约缺失、fragment 未注册均启动即抛；`compose` 拒绝 `kind=task`；CRLF 与 LF 的同一版本 hash 相同；盖章三键进入 payload 且透传到 trace。
- **核对点**：全量测试不改旧测试一行仍绿；守卫有负例；`trace` 的内容往返测试没有因新 payload 键失败（若失败即停，见第八节）。

### CP2 world 增量字段化（只加不删）

- world 新增：`neighbors` 的结构化版本、`Facts` 上的地形格（`cells`，由 `TerrainMap` 提供）、选项排布与附注的结构化字段、`BattleStatus`、观测限制的结构化标志。`task_perception.py` 同时填新旧字段。
- `ActMemory` 的 world 快照副本同步新增字段（默认值使旧数据仍可读）；`test_facts_dual_copy_parity` 扩展到新字段。
- 新增 `tests/prompt/legacy_adapter.py`：把历史输入（文本形态）适配成带结构化字段的形态；配套往返测试，证明「适配后用新字段渲染 = 旧文本」。**注意：此时新渲染器还不存在**，往返测试先以 world 自带的旧 `render` 为准，验证适配出的结构化字段能生成与旧字符串字段相同的文本（用 `TerrainMap.render()` / `render_neighbors()` / `PlaceInWorld.render()` 等既有函数，作为 CP3 起新渲染器的目标）。
- MCP 序列化与契约测试同步。
- **核对点**：旧测试不改仍绿；适配器对 CP0 对拍集的成功率与跳过原因如实汇报；world 线上数据（新旧字段）同帧一致。

### CP3 记忆渲染入模块，迁 `verify`、`summarize`、`summarize_task`、`summarize_run`

- 模块内实现 ActRecord / TaskRecord / EpisodeRecord / RunRecord 的渲染（含相邻帧去重）与观测快照渲染；四个任务各建 `v1`；md 里写全部文本与标签，函数只含逻辑。
- 四个能力对象改走「转字段 → 网关 → 盖章」。
- **核对点**：四个任务对拍集逐字节一致；这四处不再引用 `direct.prompts`；`ActMemory.render` 等旧方法仍在（尚有 `judge` 等调用方）。

### CP4 迁 `judge_success`、`decompose`、`run_plan`，抽出共用片段

- 片段单元：`read_screen`、`human_note`、`last_judge`、`goal_table`、`task_table`、`judge_interrupt`。
- 模块内实现观测渲染（读结构化字段）与 `TakeoverView` 九个视图的渲染。
- `knowledge_query.py` 不再拼 `obs.status`，改为 `scene`、`overlay`、`map_id` 与目标；行为变化在 changelog 单独说明。
- **核对点**：三任务（含 task / episode / run 三层判定与 `allow_interrupt`）对拍一致；`judge` 不再向 `decompose` / `run_plan` 借函数。

### CP5 迁 `decide_action`（5a / 5b）

- **5a**：`decide_action` 的 md 收编 `decide_action.md`、`button_help.md`、`map_hint.md`、`repeat_hint.md`、读图范例；按 overlay 选段，`terrain_legend` 的排版由 md 承担、符号表由入参 `terrain_meanings` 提供；`decide_action_retry` 单列。`MAP_HINT` / `BUTTON_HELP` / `REPEAT_HINT` 消失；`ActionSpace` 去掉 `descriptions` / `note` / `map_note`，`mcpclient/action_space.py` 不再补文案；MCP 契约、`docs/mcp/` 与相关 4 个测试同步。
- **5b**：`task_frame` 的按场合投影、`known_objects` 渲染（harness 改传原始事件，`harness` 对 `direct.prompts` 的 import 清零）、脚本签名排版并入。
- **核对点**：对拍一致；`BrainTool` 内不再有旧 `build_prompt` 调用。

### CP6 world 与记忆收缩（只减不加）

- 删除旧字符串字段与全部 `render` / `index_line` / `signature` / `render_*`；`ActMemory` 快照副本去旧字段，`test_facts_dual_copy_parity` 改写其意图。
- 同步消费方：`direct/trace/render.py` 对 `status` 的使用；reviewer 为界面渲染 `index_line` 改为自管；decode eval 与其真值数据集改为比对结构；`choose_review` 改读 `cells`；`agent_short_goal_run` 里读 `option_details` 的规则改读结构化字段。
- 删除 `memory/` 下旧记忆（需到时向用户申请删除授权）。
- **核对点**：删除前逐项查读方，读方清零才删；对拍集经适配器后仍逐字节一致（适配器此时可退役或保留为测试专用）。

### CP7 收口

- 删除 `direct/prompts/` 整包；`evals/common/legacy_requests/` 中冻结的 prompt 副本改为指向历史注册表或直接删除。
- 守卫全开：唯一出口、依赖为零、无模块级 prompt 常量、无旧符号残留。
- 同步 `AGENTS.md` / `CLAUDE.md` 第二、四、六节与 `docs/spec/` 相关页。
- **核对点**：intent 第八节八项全部机械通过。

## 六、测试清单

**新增**（`tests/prompt/`，目录镜像被测包）：

- `test_golden_baseline.py`（CP0；CP3 起改为经网关渲染并与同一份 golden 比对）。
- `test_gateway.py`、`test_registry.py`、`test_meta_hash.py`（CP1）：用法示范风格，Arrange / Act / Assert 三段。
- `test_compose.py`（CP1/CP4）：fragment 组合与 `kind` 约束。
- `test_<task>.py`（CP3–CP5）：每个任务一个，展示最简正确用法。
- `test_legacy_adapter.py`（CP2）：往返证明。
- `test_boundary_guards.py`（CP1/CP7）：调用守卫脚本。

**改写**：

- `tests/direct/prompts/*`（3 个文件）在对应任务迁移时转为 `tests/prompt/` 下的同任务测试，旧文件随 CP7 删除。
- `tests/world/test_facts_dual_copy_parity.py`（CP2 扩展、CP6 改写）。
- `tests/mcpclient/action_space/test_action_space.py`、`tests/mcpclient/world_tool/test_world_mcp_contract.py`（CP5a）。
- 引用 `.render()` / `index_line` 的 `tests/harness/**`（5 个文件）按迁移进度逐步改写。

**不新增**：真实模型测试；mock 套 mock 的测试。

## 七、验证方式

- 唯一的「正确」判据是**对拍逐字节一致**；任何差异都当作缺陷。
- 全程**不调用真实模型**，无费用需确认。
- 每个检查点做**破坏验证**：临时改坏一处（例如改动 md 中一个标点、或篡改一个 hash），确认指定用例失败，再还原，`git diff` 生产目录为空。
- 每个检查点汇报前：全量 `pytest`、`ruff check`、`ruff format --check` 三项全绿。

## 八、停止条件

执行方遇到下列情形立即停下汇报，不重试、不绕过：

1. 对拍出现任何逐字节不一致，且无法在本检查点允许改动的文件内修复。
2. CP0：任一家族的有效历史用例少于 10 条；或历史请求既不能验证为当前信封、也不能验证为旧类。
3. CP1：`trace` 的内容往返测试或 Langfuse 映射因新增 payload 键而失败。
4. 需要改动「允许改动文件」之外的文件；或需要执行被禁止的 git 命令。
5. HEAD 或关键哈希与消息中给定的不一致；起点不是全绿。
6. 需要任何真实模型调用。
7. CP2：适配器无法无损还原的样本超过对拍集的 20%。
8. 发现某个 `render` 在 prompt 之外还有未登记的读方。

## 九、已知观察（探针发现，不冻结为正确预期）

- `ModelCall.payload` 的值类型是 `str | float | list[str]`，三个版本键都是字符串，类型上可直接写入。
- `with_prompt_text` 在客户端调用，world server 的返回里 `descriptions` / `note` / `map_note` 恒为空；删除这些字段改变的是共享的 `ActionSpace` 模型，server 与 client 同仓，不涉及兼容。
- `ActMemory._render_obs` 在记忆快照里把 `walk_map` 置空再渲染；CP3 的快照渲染必须保留这个行为。
- `decide_action` 的 `retry_prompt` 在解析类失败时才追加纠正说明，传输失败原样重问；该分流逻辑在 `brain_tool._retry_prompt`，迁移不动它。

## 十、非目标

- reviewer 的 prompt 与渲染（自管）。
- 任何措辞改动、热更新、版本参数、按流量路由。
- world 的 RAM 解码（`screen_text.render_screen` 等）与 `TERRAIN_MEANING` 符号表。
- `ActionEntry.description` / `ScriptParam.description`。
- 真实模型运行；评测数据的重新采集。
