# brain —— 模块规格

> 最后更新：2026-09-23 ｜ 活文档：跟随代码更新，与代码冲突时以代码为准

## 一、职责与边界

`pokemon_agent/brain/` 是**纯决策层**，按"可整体拷走复用的第三方模块"对待。

- **无状态**（铁律 1）：`Brain.__init__` 只存注入的四个 provider，没有跨步骤的实例变量；每个方法的全部输入都来自参数。
- **只认自己声明的契约**（铁律 2）：不 import `harness` / `world` / `memory` / `trace` / `tools`；唯一横向依赖是 `brain/interface/llm_provider.py` 的两个 provider 协议与 `brain/errors.py` 的 `BrainError` 家族——后者**不继承 `AgentError`**。
- **收裸字段**（铁律 3）：入参只有 `str` / `Sequence[str]`，不认识任何 `*Req` 信封；需要结构的三处是 `keys`（校验动作合法性）、`images`（base64 PNG）、`entries`（`verdicts` 的 `index` 落回它的下标）。
- **prompt 是规则，入参是素材**：怎么判、怎么想、怎么规划全在调用方渲染好的 `prompt` 里，`Brain` 不拼 prompt、不知道 `tools/prompts/` 存在；出参是 brain 自己的方言，唯一转换点是 `tools/brain_tool.py`。
- **七个方法都是"问一次"**（`reflect` 不调模型）：内部不重试，失败抛 `AttemptFailed` 家族并携带这次尝试的 `ModelCall`；重试循环住 `tools/brain_tool.py::_attempt_loop`，预算住 `pokemon_agent/config.py`（`BRAIN_MAX_ATTEMPTS`）。

## 二、目录结构

```
brain/
├── __init__.py                统一出口；数据形状 + BrainLlmConfig 立即加载，Brain / BrainPort / build_llm_providers 经 __getattr__ 懒加载
├── brain.py                   Brain：BrainPort 的唯一实现（七个方法 + 内部解析器）
├── build_llm_providers.py     接线工厂 build_llm_providers() + 两个温度常量
├── providers.py               _OpenAICompatibleBase / _MultimodalMixin、三个厂商类、provider_for() 与 _PROVIDER_PREFIXES 选型表
├── errors.py                  BrainError 家族（解析 / 传输 / 被拒三类 + AttemptFailed 家族）
├── interface/                 统一出口：brain_port.py（BrainPort）、llm_provider.py（两个协议）、llm_config.py（BrainLlmConfig）、domain/（第四节的领域模型）
└── schemas/                   brain 的内部补全信封：LlmComplete{Req,Resp}、VisionDescribe{Req,Resp}
```

## 三、对外契约

### 3.1 `BrainPort`（`brain/interface/brain_port.py`）

`@runtime_checkable Protocol`，七个方法，一律以 `prompt` 打头、可选 `images` 收尾。

| 方法 | 签名 | 前置条件 | 承诺（后置） | 失败 |
|---|---|---|---|---|
| `choose` | `(*, prompt, keys: Sequence[str], images=()) -> ChooseResult` | `keys` 非空 | `action.sequence` 每段 `name` 都在 `keys` 内；`calls` 恰好一条 | `DecisionAttemptFailed` |
| `reflect` | `(*, prompt, before, after, action_text) -> Reflection` | `before` / `after` 非空 | `Reflection` 四字段与入参一一对应 | 不调模型，只在调用方违约时 assert |
| `judge` | `(*, prompt, goal, history: Sequence[str], images=()) -> JudgeResult` | — | `done` 是模型明确给出的布尔裁决；`calls` 恰好一条 | `JudgeAttemptFailed` |
| `plan` | `(*, prompt, goal_stack: Sequence[str], history: Sequence[str], max_push: int) -> PlanResult` | — | `calls` 恰好一条 | `PlanAttemptFailed` |
| `decompose` | `(*, prompt, goal, context: Sequence[str], max_tasks: int) -> DecomposeResult` | `max_tasks > 0` | `decomposition.tasks` 至少一条；`calls` 恰好一条；纯文本，走 plan provider | `DecomposeAttemptFailed` |
| `verify` | `(*, prompt, entries: Sequence[str], goal, knowledge, images=()) -> VerifyResult` | — | `verdicts` 与 `entries` 等长且按 `index` 顺序；`calls` 恰好一条 | `VerifyAttemptFailed` |
| `summarize` | `(*, prompt, goal, history: Sequence[str], success: bool, steps: int, max_steps: int, images=()) -> SummarizeResult` | `history` 只装已过滤的可信记录且至少一条 | `summary` 非 `None`；`calls` 恰好一条 | `SummarizeAttemptFailed` |

**统一约定（改前必读）：**

- `images` 元素一律是 **base64 编码的 PNG 字符串**，brain 这层不做编解码；空序列表示纯文本，`choose` / `judge` / `verify` / `summarize` 带图且模型多模态可用时走 `describe()`，否则 `complete()`；`plan` / `decompose` 不接图（0915 129）。
- **失败必抛、不许降级**：`done=False` / "全部标不可靠" / `summary=None` 这三种吞法会让"链路坏了"与"业务结论就是如此"在数据里分不开（trace 里只看到成功率悄悄变 0）。
- **模块层不重试**：重试是循环控制，"失败之后怎么办"取决于调用方的处境。
- 签名里被收下但不读的素材（`goal` / `history` / `max_push` / `knowledge` / `goal_stack` / `success` / `steps` / `max_steps`）立的是"这件事必须有这几块"这个约定——本项目已把它们渲进 `prompt`，不两处传。
- `verify` 只判不过滤，谁想用可信的那部分自己筛（`summarize` 收的就是筛完的）。

### 3.2 两个 provider 协议（`brain/interface/llm_provider.py`）

```python
@runtime_checkable
class LLMProvider(Protocol):
    def complete(self, req: LlmCompleteReq) -> LlmCompleteResp: ...

@runtime_checkable
class JudgeProvider(LLMProvider, Protocol):
    def describe(self, req: VisionDescribeReq) -> VisionDescribeResp: ...
```

- `complete`：前置 `req.prompt` 非空；后置 `text` 可以是任意字符串（含不合法 JSON），格式由调用方负责；失败抛异常，不返回空的 `LlmCompleteResp`。**`LlmCompleteReq` 是纯文本信封、不收图**（0915 129 定案）——带图与否的路由不在 provider 内部。
- `describe`：前置 `req.images` 至少一张且 `req.prompt` 非空；失败抛异常，**图静默未送达时必须抛 `ImageNotDelivered`**（判据 `input_tokens < floor`，`floor = IMAGE_TOKEN_FLOOR * len(images)`，`IMAGE_TOKEN_FLOOR = 100`）。
- **带图路由是一张转发表，在 `Brain` 这一层**（0915 129）：provider 实例带 `multimodal: bool`（"这个型号看不看得见图"，`_OpenAICompatibleBase` 构造参数，默认真；接纯文本型号时装配处显式传假）。`choose`/`judge`/`verify`/`summarize` 带图且 `multimodal` 为真 → `describe()`；否则 `complete()`。`plan` 是纯文本链，不接图。

## 四、数据形状

brain 方言（`brain/interface/domain/`），全部 `pydantic.BaseModel`，零依赖。

| 形状 | 关键字段 | 谁产出 | 谁消费 |
|---|---|---|---|
| `Action` / `ActionSegment` | `thought`、`sequence: list[ActionSegment]`；段有 `name` / `times`（默认 1）/ `rationale: list[str]` | `Brain.choose` | 世界执行（经 tool/harness 转换）、trace / 记忆 |
| `Goal` / `Task` | `goal` + `criteria`；`task_id` / `goal` / `success_criteria` / `max_steps` / `initial_state_hint` | 任务来自 `experiment/tasks.py`，经 harness 递给大脑 | harness 渲染进 prompt、`world` 的 `reset()` |
| `RunPlan`（内嵌 `PlanGoal` / `PlanUpdate`） | `push_goals`、`updates`、`why`（不再有 `done`：停判归 review_and_judge）；`PlanGoal` 有 `goal` / `success_criteria` / `max_steps`（task 数上限），`PlanUpdate` 有 `index` / `status` / `note` | `Brain.plan` | harness 的目标表（`task_id` 由 harness 生成） |
| `Reflection` | `before`、`rationale`、`action_text`、`after` | `Brain.reflect` | tool → step 记忆 |
| `Decomposition`（内嵌 `PlannedTask`） | `tasks`（`goal` / `success_criteria` / `max_steps`=键数上限，至少一条）、`why` | `Brain.decompose` | harness 编 `task_id` 后成为 `Task` 链 |
| `EpisodeSummary` | `summary`、`reason`（LLM 写的结论说明）、`quality_score`（0.0–1.0）、`quality_rationale`、`markdown` 等 | `Brain.summarize` | tool 配五个来源章 → `EpisodeMemory` |
| `VerifyVerdict` | `index`、`positive`（符合 goal = 正样本）、`why` | `Brain.verify` | 正负两组都交给 summarize 当参考，不过滤 |
| `ModelCall` | `payload: dict[str, str]`、`error_kind`、`error` | `Brain` 七个方法 | `tools/brain_tool.py::_adopt()` |
| 六个结果袋：`ChooseResult` / `JudgeResult` / `PlanResult` / `DecomposeResult` / `VerifyResult` / `SummarizeResult` | 硬性字段（`action` / `done`+`why` / `plan` / `decomposition` / `verdicts` / `summary`）+ `calls` + `extra` | `Brain` 对应方法 | `BrainTool` 对应方法 |

**关键不变式：**

- 六个结果袋同形：硬性字段 + 底座 `_ResultBase.extra`；写 `extra` 的判据是"调用方不必为了继续而读它"——一旦某字段"没有它就没法继续"，它该升格成硬性字段。
- **一次模型调用 = 一条账**："试了几次" = `len(calls)`，账里没有 `attempt` 字段；`ModelCall.payload` 的 `ok` 一律小写 `"true"` / `"false"`，`error_kind` 空串表示这次成功。
- `RunPlan` 用**表内序号**寻址（`PlanUpdate.index`），不认 `task_id`；`status` 只允许 `"pending"` / `"abandoned"`，`completed` / `failed` 是 harness 从结算推导的机械事实。
- `Action` / `ActionSegment` **不带任何上限常量**：段数、次数、论据条数的上限是调用方（tool/harness）的校验策略。论据挂在**段**上；顶层出现 `rationale` 是旧格式，`_parse` 直接抛 `ParseFailure`。
- `EpisodeSummary` **没有 `filename`**，`Reflection` **没有 `episode_id` / `step`**——轨迹坐标由调用方盖章。

## 五、依赖边界

### 出边（brain → 外面）

`pokemon_agent.*` 依赖为零。全部外部 import 只有标准库（`base64`、`collections.abc`、`concurrent.futures`、`dataclasses`、`io`、`importlib`、`json`、`math`、`os`、`pathlib`、`typing`、`urllib`）与第三方（`pydantic`、`PIL`）。

### 入边（谁依赖 brain）

**实现依赖的答案只有 `tools/`**：

| 位置 | 引了什么 |
|---|---|
| `pokemon_agent/tools/brain_tool.py` | 顶层：`Action` / `ActionSegment` / `BrainPort` / `EpisodeSummary` / `LearnedKnowledge` / `Reflection`、`errors` 的 `AttemptFailed` / `ParseFailure` / `ProviderRejected`；函数体内：`Brain` / `BrainLlmConfig` / `build_llm_providers` |
| `pokemon_agent/tools/vision_factory.py` | 函数体内 `brain.providers.provider_for`（给 `world` 造感知 provider） |
| `pokemon_agent/tools/game_tools.py` | `brain.errors.ProviderRejected` |
| `pokemon_agent/build.py` | **零 import**——只在注释里提型号名与工厂路径 |

**数据形状引用（不是实现依赖）**：`harness/**`（`Action` / `ActionSegment` / `Goal` / `Task` / `RunPlan`）、`schemas/harness/communication/**`（`Goal` / `Action` / `RunPlan` / `EpisodeSummary` / `VerifyVerdict` / `Task`）、`pokemon_agent/tools/prompts/decide_action.py`、`pokemon_agent/tools/trace/render.py`、`tests/**`。`world/**` 对 brain **零 import**——它只在 docstring 里提 `QwenProvider` 被当 `VisionProvider` 用，那条依赖由 tool 层接线。

## 六、接线与选型

`build_llm_providers(config: BrainLlmConfig) -> tuple[LLMProvider, JudgeProvider, JudgeProvider, LLMProvider]` 返回 `(decide, judge, verify, plan)`——顺序即 `Brain.__init__` 的形参顺序，可写 `Brain(*build_llm_providers(config))`。四条链路是**四个不同的实例**（出口 assert 保证）；型号名前缀不在选型表里时抛 `ValueError`，在装配期炸而非拖到 404。温度是**常量不是旋钮**：`DECIDE_TEMPERATURE = 0.3`、`DETERMINISTIC_TEMPERATURE = 0.0`（后者用于 `judge` / `verify` / `plan`）。

`BrainLlmConfig`（`brain/interface/llm_config.py`，`@dataclass(frozen=True)`）：

| 字段 | 默认值 | 喂给 |
|---|---|---|
| `text` | `"qwen-plus"` | `choose()` |
| `judge` | `"qwen3.8-max"` | `judge()` |
| `verify` | `"doubao-seed-2-1-pro-260628"` | `verify()` / `summarize()` |
| `plan` | `"doubao-seed-2-1-pro-260628"` | `plan()` |
| `max_tokens` | `25600` | 四个 provider 共用 |

厂商名只出现在默认值里；"哪条链路该接哪家"的知识在 `brain/build_llm_providers.py`。调用方是 `tools/brain_tool.py::BrainTool.build(...)`——**按需**：只传该层要的型号名，未传的位置 provider 为 `None`（0922 185）。它内部构造 `BrainLlmConfig`，装配点因此对 brain 零 import。

`brain/providers.py` 的三个厂商类（都继承 `_MultimodalMixin` + `_OpenAICompatibleBase`，`complete()` 与 `describe()` 都有）：

| 类 | `BASE_URL` | `API_KEY_ENVS`（按序取第一个非空） | `model` 默认 |
|---|---|---|---|
| `QwenProvider` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `("DASHSCOPE_API_KEY", "ANTHROPIC_AUTH_TOKEN")` | `"qwen3.8-max"` |
| `ArkProvider` | `https://ark.cn-beijing.volces.com/api/v3` | `("ARK_API_KEY",)` | 无（必须显式传带日期后缀的豆包型号名） |
| `DeepSeekProvider` | `https://api.deepseek.com` | `("DEEPSEEK_API_KEY",)` | `"deepseek-flash"` |

- `provider_for(model, *, temperature, max_tokens=None, timeout=45)` 按 `_PROVIDER_PREFIXES`（顺序 `deepseek` → `doubao` → `qwen`）选类，是"型号名 → 厂商类"的唯一判据；本模块的工厂与 `tools/vision_factory.build_vision_provider()` 共用它。
- `_disable_thinking_payload()` 必须被子类覆盖：Qwen 用扁平布尔 `{"enable_thinking": False}`，Ark 与 DeepSeek 用嵌套对象 `{"thinking": {"type": "disabled"}}`。
- 一次调用 = 一次 HTTP 请求，provider **不重试、不重发**；4xx → `ProviderRejected`（调用方立即耗尽预算），5xx / 网络层 / 单请求总时长超闸 → `ToolTimeout`。
- 密钥只从环境变量读；`config()` 自报配置进 run manifest，不含 key。

## 七、当前状态与已知缺口

- `reflect()` 本版**不调模型**（`prompt` 收下不消费），为形状统一预留位置。
- `brain/providers.py` 有模块级可变全局 `_dump_seq`（配合环境变量 `VISION_DUMP_DIR` 的排查落盘序号）——铁律 1 说"不许有模块级可变全局"，这是全模块唯一一处，且只影响调试文件名。
- 约束解码未上；模型给的 markdown 代码围栏由 `brain/brain.py` 的模块级私有函数 `_strip_json_fence` 剥掉，不做任何内容修复。
- `brain/schemas/vision.py` 与 `pokemon_agent/world/interface/domain/vision_describe.py` 是同构的两份，靠"字段名人工核对"保持一致，没有机器检查。
- `scripts/` 下**没有** brain 专用的自包含检查脚本（只有 `check_trace_self_contained.py` 与 `check_world_self_contained.py`），"出边为零 / 装配点零 import"目前靠人工核对。
