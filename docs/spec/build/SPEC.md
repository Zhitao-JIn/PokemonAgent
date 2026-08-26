# Pokemon Agent 技术规格：装配、错误体系、实验记录与观测层

本文档基于源码（含中文注释中的设计动机）梳理以下六个文件，并说明它们如何串成
"从命令行到真实跑一局"的完整调用链：

- `pokemon_agent/build.py`
- `pokemon_agent/errors.py`
- `pokemon_agent/experiment/manifest.py`
- `pokemon_agent/trace/store.py`（`LocalTrace`，原 `pokemon_agent/mocks/mock_trace.py`，已迁移）
- `pokemon_agent/trace/utils.py`（`trace_utils`，新增——见 `interfaces/SPEC.md` 第 4 节、`harness/SPEC.md` 4.5/4.17 节）
- `probe/run_episode.py`

> **`probe/echo_trace.py`（`EchoTrace` 装饰器）已删除**，不再是本文档覆盖范围。
> 控制台打印逻辑并入了 `LocalTrace.sse()`——`TracePort` 协议新增了 `sse` 方法
> （推流，"现在是控制台，以后是浏览器"），`append()` 的实现在落盘后自动调
> `sse()`，不再需要一层外部装饰器。第 4、6 节已按此重写。

---

## 1. `pokemon_agent/build.py` —— 全项目唯一的装配点

### 1.1 模块定位

模块 docstring 明确了一条项目约定（CLAUDE.md 第三节第 3 条）：**这是全项目唯一一处
`new` 具体实现的地方**。理由是把"怎么拼起来"（build.py）和"怎么互相调用"
（`harness/harness.py`）分开放，避免像上一版那样把两者塞进同一个
`graph/build.py`，导致"图认识 LLM"这种耦合——图（控制循环）不应该知道具体用的是
哪个 LLM provider，只应该拿到端口（Port）接口。

文件头部给出了装配关系图：

```
Harness  控制循环   ──→ GameToolPort   ──→ WorldPort ──→ PyBoyWorld ──→ VisionProvider
                    └─→ MemoryToolPort ──→ memory/（语义记忆）
                    └─→ BrainPort      ──→ LLMProvider
                    └─→ TracePort
```

图（控制循环）本身没有一行代码碰得到 provider：provider 都是通过构造函数注入的，
只有 `build.py` 这一处 `import` 具体类（`QwenText`、`QwenVision`、`PyBoyWorld`、
`GridOverlay` 等）。

### 1.2 为什么曾经有 `build_demo`，现在删了

曾经存在一个 `build_demo`（用 `MockWorld` + `FakeLLM` 拼出的离线最小闭环，用来在没有
真实模拟器/模型接入时跑通链路）。真实环境（PyBoy + 真实 LLM）接进来之后，这个函数被
删除。理由写在 docstring 里：留着两条装配路径，等于留着一条"没人真的跑"的代码路径——
即无人维护、会逐渐与主链路脱节的死代码，删除是刻意的清理动作而非疏漏。

### 1.3 `build_real()` 函数签名与参数表

```python
def build_real(
    rom: str,
    state_path: str | None = None,
    *,
    vision_model: str = "qwen3-vl-plus",
    text_model: str = "qwen-plus",
    judge_model: str = "",
    max_tokens: int = 25600,
    watch: bool = False,
    grid: bool = True,
    trace: TracePort | None = None,
) -> tuple[Harness, TracePort, PyBoyWorld]:
```

| 参数 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `rom` | `str` | 必填 | ROM 文件路径，交给 `PyBoyWorld` |
| `state_path` | `str \| None` | `None` | 存档路径；`None` 表示不加载存档，从 ROM 开头跑 |
| `vision_model` | `str`（关键字） | `"qwen3-vl-plus"` | 感知（视觉）链路用的模型，走"最便宜的视觉模型" |
| `text_model` | `str`（关键字） | `"qwen-plus"` | 决策链路用的文本模型，"走有资源包的文本模型" |
| `judge_model` | `str`（关键字） | `""` | 判定链路用的模型；空字符串表示与 `text_model` 同型号 |
| `max_tokens` | `int`（关键字） | `25600` | 决策与判定两条链路**共用**的输出 token 上限 |
| `watch` | `bool`（关键字） | `False` | 是否开窗口实时观看（不影响 agent 行为，只影响人能否看见） |
| `grid` | `bool`（关键字） | `True` | 是否给视觉模型的输入图叠加网格辅助线（`GridOverlay`） |
| `trace` | `TracePort \| None`（关键字） | `None` | 传入的 trace 实现；为空则用 `LocalTrace()` 兜底 |

返回值：`tuple[Harness, TracePort, PyBoyWorld]` —— 装配好的控制循环、trace 实例、
世界对象。

### 1.3.1 内部装配步骤

```python
from pokemon_agent.providers.dashscope import QwenText, QwenVision
from pokemon_agent.vision.preprocess import GridOverlay

vision = QwenVision(model=vision_model, preprocess=(GridOverlay(),) if grid else ())
world = PyBoyWorld(rom, vision, state_path=state_path, watch=watch)
trace = trace or LocalTrace()

game = GameTools(world)
memory = MemoryTool()
brain = Brain(
    decide_llm=QwenText(model=text_model, max_tokens=max_tokens),
    judge_llm=QwenText(model=judge_model or text_model, max_tokens=max_tokens),
)
return Harness(game, memory, brain, trace), trace, world
```

1. **组建视觉 provider**：`QwenVision`，按 `grid` 开关决定是否挂 `GridOverlay` 预处理。
   `import` 延迟到函数体内部（而非模块顶部），使 `build.py` 顶层不强依赖具体的
   `providers.dashscope` / `vision.preprocess` 模块。
2. **组建世界**：`PyBoyWorld(rom, vision, state_path=state_path, watch=watch)`，把视觉
   provider 注入世界对象。
3. **确定 trace**：调用方传入的优先，否则退回 `LocalTrace()`。
4. **组建工具层**：`GameTools(world)` 只碰 world；`MemoryTool()` 独立存在，与
   `GameTools` 互不相识——"组合是 `Harness` 的事"。
5. **组建大脑**：`Brain` 接收 `decide_llm` 和 `judge_llm` 两个**各自独立构造**的
   `QwenText` 实例（即便模型名相同也不共用一个 provider 对象）。
6. **组建控制循环**：`Harness(game, memory, brain, trace)`。

### 1.4 三个模型分开的设计理由（源码原文归纳）

不是"设计洁癖"，而是由计费结构和实验方法共同决定：

- **决策**走有资源包的文本模型；
- **感知**每步都调、任务简单，走最便宜的视觉模型；
- **判定**必须和决策分开，否则就是误差同源（详见 `brain/brain.py`）。即使型号相同，也要
  **各建一个 provider 实例**：原因有二——
  1. 共用一个实例的话，将来想单独给判定换模型，就得改两处代码；
  2. 若 manifest 里两条链路指向同一个 provider 对象，从记录上就看不出它们本来是可以
     分别选型的。

### 1.5 `trace` 参数与 `LocalTrace`

`trace` 参数默认走 `LocalTrace()`（`pokemon_agent/trace/store.py`，原先住在
`pokemon_agent/mocks/mock_trace.py`，已搬到独立的 `trace/` 包下）——内存列表，
不落盘。docstring 明确指出：落盘、replay、checkpoint 是"阶段 2"的事；在那之前
跑出来的数据**进程一退就没了**，只适合调试，不适合正式实验积累。

`LocalTrace` 现在**自带控制台打印**：`append()` 落盘之后会自动调 `self.sse(event)`，
`sse()` 就是打印实现本身（不再需要外面套一层 `EchoTrace` 装饰器，见第 4、6 节）。

### 1.6 `brain` 拿不到 `trace`，也拿不到 `tools`/`memory`

`Brain` 构造时只接收两个 LLM，不接收 trace、`game`、`memory`。docstring 解释：
"写 trace 是 Harness 一个人的事，检索记忆也是"——大脑只把账（`ModelCall`）连同结果
交出去，由 `Harness` 负责把它翻译成 trace 事件，职责边界清晰。

### 1.7 `max_tokens` 为何决策与判定共用一个上限

判定每次只输出二三十个 token，抬高上限对它没有实际影响；如果为判定单独开一个配置项，
就只是多出一个"没人调的旋钮"，属于无谓的复杂度。

### 1.8 网格叠加为什么挂在 provider 上而不是 world 上

网格是"给模型看的辅助线"，不是画面本身的一部分，所以挂在 `vision` provider 的
`preprocess` 上；`world` 交出去的、用来存证、将来给 CV 通道用的，仍然是未经网格叠加的
原图。

### 1.9 为什么返回 `world`

返回 `world` 是为了让调用方能显式 `world.stop()`：模拟器是进程级资源，"谁开的谁关"，
`Harness` 不该越权管理它的生命周期。`probe/run_episode.py` 的 `main()` 正是在
`finally` 块里调用 `world.stop()`。

---

## 2. `pokemon_agent/errors.py` —— 预期内的失败

### 2.1 划分原则

模块 docstring 引用 CLAUDE.md 第八节的原则：**调用方违约用 `assert`，外部世界不配合
用这里定义的异常**。

每一类失败单独成一个异常类，是因为 replay 阶段要"按失败类型归类统计"——"修了 Z
类失败模式"这句话里的 Z，就是这个文件里定义的异常类的数量。

### 2.2 `AgentError`（基类）

```python
class AgentError(Exception):
    """本项目所有预期内失败的基类。捕获它意味着"我知道这里会出问题"。"""
```

作为基类的意义：捕获 `AgentError` 是一个显式声明——"我预期这里会失败，并且知道怎么
处理"。`probe/run_episode.py` 的 `main()` 就是这样使用它的：

```python
try:
    outcome = harness.run(episode_id, task)
    ...
except AgentError as e:
    print(f"\n提前终止：{type(e).__name__}: {e}")
finally:
    world.stop()
```

即：`run_episode.py` 把整个 `AgentError` 家族统一当作"episode 提前终止但进程本身
应该体面收尾"的情况来处理，无需逐个类型分别捕获。

### 2.3 各子类

| 异常类 | 构造参数 | 用途 | 与谁区分、为什么要分开 |
|---|---|---|---|
| `ParseFailure` | `raw_text: str, reason: str` | LLM 输出无法解析成 `Action`。是**最常见**的一类失败，且可重试。保留原始文本是为了 replay 时能看清模型到底吐了什么（截断前 200 字符存入异常消息） | 与 `OutputTruncated` 严格区分：二者在下游"少个右括号"的表现完全一样，但修法相反（前者改 prompt / 上约束解码，后者调大 `max_tokens` 或让模型少说）；混成一类会让统计里永远看不见截断问题 |
| `IllegalAction` | `name: str, allowed: list[str]` | LLM 选了一个不在 action space 里的动作，属于**大脑内部**发现的模型幻觉，是"外部输入不合法"→异常+重试 | 与 `execute()` 入口的 `assert` 不冲突：那个 assert 防的是"大脑没检查就把非法动作递出去"（调用方 bug）；这里防的是模型本身选错——两道防线针对两个不同责任方 |
| `OutputTruncated` | `tokens: int` | 模型输出被 `max_tokens` 硬切断，`finish_reason == "length"`。判据来自服务端返回的 `finish_reason`，**不是**拿 token 数去猜 | 与 `ParseFailure` 分开的理由见上表。实测案例：一次调用烧了 23 秒、产出为零、错误信息还指错方向 |
| `MaxRetriesExceeded` | `attempts: int, last_reason: str` | 连续重试仍拿不到合法动作，说明模型在当前状态下持续失败。这是一条要进 trace 并被 replay 统计的失败模式，不是"再试试就好" | —— |
| `ImageNotDelivered` | `input_tokens: int, floor: int` | 图片没有真的送到模型，但网关（实测于 DashScope 的 Anthropic 兼容端点）不报错、返回一段读起来合理但其实是凭空编造的描述。判据是**输入 token 数**（塌回纯文本量级即为铁证），不是回答内容本身是否合理 | 走异常而非 `assert`：这是"外部世界不配合"而非调用方违约；单独成一类而不是并入 `ParseFailure`：在 replay 里它是独立的失败模式，且是唯一一种"不修就会让全部实验数据静默作废"的类型，必须在统计里一眼可见 |
| `PerceptionFailure` | `attempts: int, last_reason: str` | 反复调用视觉模型仍拿不到能解析的 `ScreenState`，属于感知层问题 | 与 `ParseFailure` 分开：那是大脑（决策）的输出格式问题；这是感知层的（换模型、改预处理，或这一帧本来就没法读）。与 `ImageNotDelivered` 也分开：后者是图没送到（网关问题），前者是图送到了但读不出结构（能力问题） |

所有子类都继承自 `AgentError`，均在 `__init__` 里把关键诊断字段（如 `raw_text`、
`attempts`、`input_tokens` 等）存为实例属性，供上层（trace 记录、replay 统计）读取，
而不仅仅是拼进异常消息字符串里。

### 2.4 抛出方与捕获方

源码本身（`errors.py`）不包含抛出/捕获逻辑，只定义类型；结合 docstring 的语境可确认：

- 抛出方：分布在大脑（`brain/brain.py`，抛 `ParseFailure`、`IllegalAction`、
  `OutputTruncated`、`MaxRetriesExceeded`）与感知/provider 层（抛
  `ImageNotDelivered`、`PerceptionFailure`）——这些具体抛出点不在本次阅读的六个文件
  范围内，未在源码中直接验证，此处不做臆测。
- 捕获方：至少确认 `probe/run_episode.py` 的 `main()` 用 `except AgentError as e`
  统一捕获整个家族，作为 episode 提前终止的处理路径。

---

## 3. `pokemon_agent/experiment/manifest.py` —— 一次实验的不变量快照

### 3.1 定位：为什么要和 trace 分两层

trace 是"每步一条"的事件流，manifest 是"每次实验一份"的快照。如果把 prompt 原文、
模型配置这类全程不变的信息塞进每一条 trace 事件，跑一万步就要重复存一万遍相同内容。

分层后各自存什么，源码给出了明确对照表：

| | 放什么 | 判据 |
|---|---|---|
| manifest | prompt 原文、模型与温度、git commit、预处理方式、**权限配置** | 全程不变 |
| trace 事件 | frame_sha、tokens、延迟、模型原始输出 | 每步都变 |

### 3.2 为什么 prompt 要存原文而不是只存 sha

`prompt_sha` 只有在"查得到内容"时才有意义。如果改了 prompt 却没提交代码就跑了实验，
那个 sha 就指向一个查无实据的虚空——三周后面对一批数字，无法确认它们对应哪一版
prompt。manifest 里直接存原文，这个依赖链就被切断了。

### 3.2b 权限配置为什么也要存原文

和 prompt 是同一个论证。`config/permissions.json` 决定 agent 能调哪些工具——
角色里少一条 `read:memory:knowledge`，这一批 run 跑的其实是"无知识库"那个消融组，
而 **trace 里没有任何字段说得出这件事**。它全程不变，所以属于 manifest 这一层；
它不在版本库里（是运行时配置），所以只存 sha 会指向虚空，得连原文一起存。

`context.json` 同理：`roles` 是实验条件本身，`subject_id` 是审计流（`log/audit.jsonl`）
里这一批 run 的身份。`metadata` 现在是空的——它曾经放着 `run_id` / `episode_id` /
`task_id` 三个字面量 `"runtime"` 占位符，从来没被填过、也没有任何读取方，
而权限流的编号现在由库自己铸（见 3b.4）。

对应字段是 `permissions: dict[str, dict[str, str]]`（`文件名 -> {sha, text}`，
和 `prompts` 同一个形状），由 `with_permissions(config_dir=Path("config"))` 收集。
`validate_design()` 断言它非空——**宁可开跑前炸，也不要事后拿到一批无法归因的数据**。

### 3.3 不存什么

明确排除 API key：它不进任何会被写出去的东西，`config()` 方法也不返回它。

### 3.4 `Configurable` 协议

```python
@runtime_checkable
class Configurable(Protocol):
    def config(self) -> dict[str, str]: ...
```

刻意**不**把"自报配置"的能力放进 `LLMProvider` / `VisionProvider` 这两个 Port
接口里。理由：Port 描述的是"能做什么"（能力），而自报配置服务于"可复现性"这个另外
的关注点。用一个独立的结构化类型（Protocol）在这里单独表达，好处是 provider 不需要
显式声明实现它（鸭子类型），Port 接口也不必因此变宽。

### 3.5 `_git_commit()`

```python
def _git_commit() -> str:
```

取当前 commit 短 hash（前 12 位），并检测工作区是否 dirty：

- 取不到 commit（非 git 环境等）→ 返回 `"unavailable"`，**不猜、不留空**——"取不到"
  本身就是有信息量的（说明这次实验跑在不可靠的可复现性环境下）。
- 取到 commit 但取不到 dirty 状态 → 只返回 sha。
- 工作区 dirty → 返回 `"{sha}-dirty"`，因为"代码和 commit 对不上时，commit 号是
  误导性的"，必须显式标出。
- 任何子进程异常都被 `except Exception` 兜底（注释 `noqa: BLE001` 说明是有意为之：
  "取不到 commit 不该让实验跑不起来"）。

### 3.6 `RunManifest` 模型（`pydantic.BaseModel`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_id` | `str` | 本次实验标识，trace 事件靠它归组 |
| `started_at` | `str` | ISO 时间戳，由调用方传入 |
| `git_commit` | `str` | 默认由 `_git_commit()` 生成 |
| `providers` | `dict[str, dict[str, str]]` | 角色 → 配置，角色至少含 `"vision"` 和 `"text"`，配置来自 `provider.config()` |
| `prompts` | `dict[str, dict[str, str]]` | prompt 名 → `{sha, text}`，**存原文** |
| `preprocess` | `str`，默认 `"native"` | 图像预处理方式（原生 vs 放大等），用于消融实验分组 |
| `notes` | `str`，默认空 | 这次实验想验证什么，"给三周后的自己看" |

方法：

- `with_prompts(*names) -> RunManifest`：批量把指定 prompt（通过
  `pokemon_agent.prompts.load` 加载）的 `sha` 和 `text` 收进 `self.prompts`，链式调用。
  **现在收三份**：`decide_action`、`judge_success`、`episode_summary`。
  最后那份是后补的：`episode_summary.md` 原来走的是另一套模板引擎
  （`EpisodeMemoryGenerator` 自己 `jinja2.Template(open(...))`，`{{ }}` 语法），
  **不经过 `prompts.load`，所以既没有 sha、也进不了 manifest**——某一局的蒸馏用的是
  哪一版说明，事后查不出来，而这正是 manifest 存在的全部意义。
  它现在改成 `$` 占位符、走同一条加载路径。
  **判断标准是"这份 prompt 影响不影响这批数据"**，不是"它在不在每步的回路里"：
  蒸馏一局只跑一次，但它决定了落库的经验长什么样。
- `with_permissions(config_dir=Path("config")) -> RunManifest`：把 `context.json` 与
  `permissions.json` 的 `sha`（sha256 前 12 位）和 `text` 收进 `self.permissions`。
  前置条件用 `assert path.is_file()` 守：这两个文件是 `agent_permission` 启动的硬要求
  （见 `harness.run()` 的 `@initialize`），跑到这里还没有就该当场停，而不是记一份空的
  权限快照、让这批数据事后无法归因。
- `with_provider(role, provider: Configurable) -> RunManifest`：记录一个 provider 的
  配置。用 `assert hasattr(provider, "config")` 断言其满足 `Configurable`；配置内容
  来自 `provider.config()` 而非让 manifest 自己认识具体 provider 类型——"装配处才是
  唯一知道具体实现是谁的地方，这里只负责抄下来"（呼应 `build.py` 的"唯一装配点"
  原则）。
- `save(path) -> pathlib.Path`：写盘为 JSON（`ensure_ascii=False, indent=2`）。
  docstring 强调**必须写在 trace 之前**："先有 manifest，后有数据"，顺序反了的话，
  实验中途崩溃会留下一堆无法归因的 trace 事件。

### 3.7 接入现状

manifest **已经接入** `pokemon_agent/experiment/run_experiment.py`：

```python
manifest = RunManifest(...).with_prompts("decide_action", "judge_success", "episode_summary") \
                           .with_permissions() \
                           .validate_design()
manifest.save(pathlib.Path("experiment_results") / run_id / "manifest.json")
```

`probe/run_episode.py` 那条调试入口仍然不生成 manifest——它跑的是单局调试，
不是要归档的实验。

`validate_design()` 现在断言四件事：`experiment_kind` 取值合法、
`memory_policy == "session_local"`、`task_ids` 非空、**`permissions` 非空**。
最后一条是硬失败：任何漏掉 `.with_permissions()` 的装配会在开跑前就炸掉。

---

## 3b. `agent_permission` —— 横切的权限层

第三方库（`github.com/Zhitao-JIn/AgentPermission`），以**装饰器**形式散布，不是本项目的一个模块。

### 3b.1 装在哪

| 位置 | 权限名 |
|---|---|
| `Harness.run()` | `@initialize`（不是检查，是每局重载配置） |
| `GameTools` 各方法 | `read:game:action_space` / `execute:game:reset` / `execute:game:press` / `execute:game:save_state` / `execute:llm:perception` |
| `MemoryTool` 各方法 | `read:memory:{episodic,episode,objects,knowledge}` / `write:memory:{episodic,episode,objects}` / `execute:llm:memory_summary` |
| `Brain.choose/judge/reflect` | `execute:llm:decision` / `execute:llm:judge` / `execute:llm:memory_reflection` |

**装在大脑上不违反铁律 2**：横切设施和"brain 不许 import harness 的具体实现"是两回事。
粒度也刻意对齐"哪一类模型调用"——挪到 `providers/` 会把五条路径塌缩成一个权限，粒度全丢。

### 3b.2 配置

从**进程启动目录**下的 `config/` 读（`Path.cwd() / "config"`）：

- `context.json`：`subject_id` / `roles` / `metadata`。
- `permissions.json`：`roles`（角色 → 权限通配列表）决定有没有；`policies` 决定有了之后要不要审批。

目前唯一挂 `approval_required: true` 的是 `execute:game:save_state`（走控制台审批，等 10 秒）。

### 3b.3 Harness 这一侧只承担一件事

**权限失败不能让这一局从 trace 里消失。** 库里四个异常
（`PermissionDenied` / `ApprovalRequired` / `ApprovalRejected` / `ApprovalExpired`）
**各自直接继承 `Exception`，没有共同基类**，所以任何"列举权限异常"的写法都会在库新增
异常类型时静默漏掉。`run()` 因此不列举，只用 `except Exception` 兜底补 `EPISODE_END`
再原样抛出——详见 `harness/SPEC.md` 6.3。

### 3b.4 已知的坑

- **`_current_context` 曾经是 `ContextVar`**，导致 worker 线程读不到身份（ContextVar 的值
  按执行上下文隔离，新线程带的是空表），症状是"并发时权限全被拒、单线程一切正常"。
  已改成普通模块全局。代价是同一进程内不能并发跑两个不同 subject。
- **`audit.jsonl` 和 trace 刻意不对齐**（曾经作为"坑"记在这里，现在是设计）。
  权限流的三个 ID 全部**由库自己生成**，三层嵌套：`episode_id`（一次 `@initialize`
  到下一次之间）⊃ `trace_id`（一次守卫调用的完整链路）⊃ `event_id`（一条记录），
  外加只在审批分支出现的 `approval_id`。它们都不接受调用方注入。

  依赖方向是**调用方读库**，不是库接调用方的坐标：真要按 episode 关联两条流，
  是 harness 读一次 `get_current_context().episode_id`、在自己的事件流里记一次映射。
  反过来（把 harness 的 `episode_id` / `step` 喂进权限库）会让库需要认识调用方的函数
  签名，而调用方还得为权限流的编号负责——耦合是白加的。当前**不需要**关联，所以
  这个映射也没记。
- **`import agent_permission` 不再有副作用**。它曾经在模块级跑 `_load_runtime()`，
  于是 import 就要读 **cwd 下**的 `config/`，从别的目录 import 直接炸。现在只有
  `@initialize` 会读——代价是第一次 `@initialize` 之前调被守卫的函数会抛
  `RuntimeError`（而不是从前那样静默退化成 `anonymous` 然后全被拒）。
  本项目所有被守卫的调用都在 `harness.run()` 之内，不受影响。

---

## 4. `pokemon_agent/trace/store.py` —— `LocalTrace`

**这个类已从 `pokemon_agent/mocks/mock_trace.py` 搬到独立的 `pokemon_agent/trace/`
包下**，与它同目录的 `trace/utils.py`（`trace_utils`）不在本节展开——那部分是纯函数、
不认识 `TracePort`，详见 `interfaces/SPEC.md` 第 4 节和 `harness/SPEC.md` 4.5/4.17 节。

### 4.1 定位

**它已经不是 mock 了。** 模块 docstring 曾经开门见山写着"它是 mock 存储"（内存列表，
进程一退就没了），类名也叫 `MockTrace`。现在它叫 `LocalTrace`，`TracePort` 的三个方法
都是真实实现：

- `append()`：分配**严格单调**的 `event_id`，**逐条追加**写进
  `trace_data/<run_id>/episodes/<episode_id>.jsonl`，再调 `sse()` 推一份出去。
  逐条追加而不是最后一次性 dump——进程被 Ctrl-C 掐掉时，已经跑过的那些步不该跟着没。
- `replay()`：按 episode 读回并按 `event_id` 排序。
- `sse()`：把事件推给观测通道（浏览器观测台 + 终端打印，见 6.5）。

**推流和落盘是同一条事件，没有第二个源头**：`append()` 里落完盘就调 `sse()`，
不给"控制台看到的"和"文件里存的"留下分叉的机会。

`event_id` 严格单调这一条是硬要求：观测台断线重连靠它补发，重号或回退会让观测台
**静默**丢事件。

仍然没做的是**按失败类型聚合统计**（没有查询/索引层，只有线性扫描），
那仍然是"阶段 2"的事。

### 4.2 打印逻辑并入 `sse()`——`EchoTrace` 已删除

以前打印和存储分在两个文件、两层对象里：`mocks/mock_trace.py` 只管存储，
`probe/echo_trace.py` 是包住它的一个装饰器（`EchoTrace`），专门负责在 `append()`
外面加一层打印。拆开的原因是当时 `TracePort` 协议里**没有"推流"这个位置**——
`EchoTrace` 只能从外面在 `append` 上加一层旁路。

现在协议本身有了 `sse()`，打印就是这个方法应该长的样子：`append()` 落盘之后自动调
`self.sse(event)`。**但今天的 `sse()` 已经不是当年 `_echo()` 的全套分支**——
七类事件（观测/记忆读/推理/动作/细看/记忆写/对象档案）**终端一个字都不打**，
只走浏览器观测台，名单在模块级的 `BROWSER_ONLY` 里。终端留给账单、错误、
目标出栈、episode 起止。详见 6.5。

**浏览器观测台是 `trace/browser.py` 的 `BrowserTraceServer`**（HTTP + 一条 SSE 长连接），
通过构造参数 `sse_sink=browser.publish` 挂进来。它有一个**进程级单例
`shared_server()`**，`build_session()` 用的是它——原来每建一次会话就 new 一台，
而端口固定 8765：Linux 上第二台直接 `EADDRINUSE`，**Windows 上更坏**——
`allow_reuse_address` 让第二次 bind 也成功，同一端口上于是有两台服务，
浏览器那个标签页还挂在第一台的连接上，**第二局的事件全推给了第二台，页面从此
一个字都不再更新**，而日志和落盘一切正常。`--repeat` 跑多局时这个 bug 每次都会犯。

### 4.3 如何实现 `TracePort`

```python
class LocalTrace:
    def __init__(self, run_id: str = "local") -> None:
        self._run_id = run_id
        self._events: list[TraceEvent] = []
        self._next_id = 0
        self._step_shown: tuple[str, int] | None = None  # sse() 用，见下
```

`run_id` 在构造时确定：一次实验对应一个 trace 实例，每条事件都归属于它。

**`append()`**：

```python
def append(self, episode_id, step, type, source, payload=None) -> int:
```

- 前置条件（`assert`）：`step >= 0`，`episode_id` 非空。
- 分配严格递增的 `event_id`（`self._next_id` 自增）。
- 构造 `TraceEvent`，把 `ts=time.time()` 由实现方自己填入——注释说明"时间戳是 trace
  的属性，不是业务参数"，即调用方不应该、也不需要传时间戳。
- 追加到内部 `list`。
- 后置条件（`assert`）：新事件的 `event_id` 严格大于上一条事件的 `event_id`。
  docstring 强调这一点的实际影响：**SSE 的断线补发完全依赖这一单调性**，一旦
  `event_id` 重复或回退，观测台会静默丢事件。
- **落盘之后调用 `self.sse(event)`**——一条事件先记下来、再推流，顺序固定。

**`replay()`**：

```python
def replay(self, episode_id: str, after_event_id: int = -1) -> Iterable[TraceEvent]:
```

- 前置条件：`after_event_id >= -1`（`-1` 表示从头开始）。
- 返回某个 `episode_id` 下、`event_id > after_event_id` 的事件，按 `event_id` 升序。
- 因为内部 list 本身就是按 `event_id` 升序追加的，不需要重新排序，直接用列表推导
  过滤即可。

**`sse()`**：

```python
def sse(self, event: TraceEvent) -> None:
```

- 把这条事件推给当前的观测通道——现在的实现是按 `event.type` 分支，往控制台打印
  一行到几行不等的格式化文本（表头/成本行/thought/action 等各有自己的排版）。
- `self._step_shown` 记的是"这一步的表头打过没有"，由 **step 值变化**触发表头打印，
  而不是挂在某个特定 `EventType` 上——挂在 `OBSERVE` 上不行，因为事件流里
  `MODEL_CALL(perception)` 在它前面（因果顺序，产出观测的调用当然更早），表头会
  打在本步的成本行下面。排版问题在这里解决，**不去改动事件流**——trace 是唯一的
  事实来源，`sse()` 只负责怎么呈现它。
- `LABEL_W = 15`（最长标签 `perception_cost` 决定的列宽）、
  `COST_LABEL: dict[Source, str]`（`MODEL_CALL` 事件按来源打印的标签，
  `perception_cost`/`decision_cost`/`judge_cost`）两个模块级常量支撑这套排版。

**契约之外的调试方法**（注释明确标注"不属于 TracePort 契约"）：

- `all_events()`：返回全部事件（含所有 episode），供测试断言用。
- `count(episode_id, type)`：统计某个 episode 里某类事件的条数，供测试断言重试次数
  / 失败次数用。

### 4.4 与真实实现的差距

这一节原来列了四条差距，前两条已经补上了：

1. ~~事件只存在内存 `list` 里，不落盘~~ → **已落盘**：逐条追加写 JSONL，
   进程被掐掉也只丢最后一条。
2. ~~`sse()` 只打印到控制台，没有真正的推流通道~~ → **已有浏览器观测台**
   （`trace/browser.py`，HTTP + SSE 长连接，断线靠 `event_id` 补发）。
3. **仍然不能作为 checkpoint 的事件源**：能按 episode 重放，但没有"从某个 event_id
   恢复状态"的机制——恢复还缺记忆库（见 `harness/SPEC.md` 1.4）。
4. **仍然不能按失败类型聚合统计**：没有查询/索引层，只有线性扫描。

后两条仍是"阶段 2"的事。

**当年那句"它是 mock，替身也必须遵守契约"的判断值得留一笔**：正因为它当初就严格
实现了 `append`/`replay`/`sse` 的完整契约（而不是留几个 `pass`），后来补落盘和补
推流才只是换 `sse()` 和 `_save_event()` 的内部实现，**调用点一处没动**。

---

## 5. `pokemon_agent/experiment/` —— 命令行跑实验

**这一节的文件搬过家**：原来是 `probe/run_episode.py`，现在是
`pokemon_agent/experiment/run_episode.py`（装配会话、跑一个 episode）和
`pokemon_agent/experiment/run_experiment.py`（真正的实验入口：选任务链、
写 manifest、`--repeat` 跑 N 遍、累积 `task_stats`）。下面的用法示例是旧的，
现在的入口是：

```
python -m pokemon_agent.experiment.run_experiment                      # 列出任务
python -m pokemon_agent.experiment.run_experiment --task-id X --repeat 10
```

`--repeat N` 的每一遍都是**一次完整独立的 run**：独立 run_id、独立 manifest、
独立 trace 目录、world 新建又关掉。不复用——复用的话第 2 遍会从第 1 遍结束的
画面开始，测的就不是同一件事了。`--repeat 1` 时 run_id 保持原样不加后缀
（`--run-id` 是拿来指名道姓找这一跑数据的），大于 1 才加 `-r1`/`-r2`。

### 5.1 旧入口的用法与注意事项（`probe/run_episode.py`，已搬走；下面几节的代码引用按旧文件读）

```
$env:DASHSCOPE_API_KEY = "sk-..."
python -m probe.run_episode                                  # 12 步，无头
python -m probe.run_episode 30 "走出真新镇，向北进入一号道路"
python -m probe.run_episode 30 "…" watch                      # 开窗口看着它玩
python -m probe.run_episode 30 "…" --state assets/route1.state --task-id t_route1
python -m probe.run_episode 30 "…" --state none               # 从 ROM 开头跑
```

默认无头（`watch=False`）：因为跑实验时墙钟是瓶颈，开窗口和限速只会拖慢速度。
`watch` 只影响人是否看得见画面，**不影响** agent 行为——agent 读取的是
`screen.ndarray`，与窗口是否打开无关。

⚠ 注意事项（源码原文）：

- 不要同时开着 `probe.play`：两个 PyBoy 实例共用同一 ROM 时，退出都会写
  `assets/rom.ram`，后退出的会覆盖先退出的。
- 每步会打印观测摘要、可用动作、大脑选了什么、为什么；结束后汇总感知与决策**各自**
  的 token 消耗——这两笔账要拆得开，是"感知走便宜模型、决策走强模型"这条成本叙事的
  依据。
- trace 是内存里的，进程一退就没了；落盘是阶段 2 的事。

### 5.2 常量

```python
ROM = "assets/rom"
STATE = "assets/rom.state"
```

`STATE` 是默认存档，用 `--state` 可以换掉。docstring 强调存档就是"任务的起点"：想让
agent 从"已经站在一号道路上"开跑，只需存一个那个位置的档并用 `--state` 指过去，无需
改任何代码。这也是让不同批次数据可比的唯一办法——同一个 `task_id` 下多次尝试起点必须
相同，否则成功率无意义；因此**存档要和 `--task-id` 一起看**：换了存档就该换
`task_id`，否则不同任务会被错误聚合成一个统计数字。`--state none` 表示不加载存档，
从 ROM 开头跑（连开场动画、命名流程都要自己走完）。

### 5.3 `_flag()` —— 极简参数解析

```python
def _flag(name: str, default: str) -> str:
    argv = sys.argv[1:]
    if name not in argv:
        return default
    i = argv.index(name) + 1
    return argv[i] if i < len(argv) else default
```

从形如 `--name value` 的参数里取值。源码注释明确了为什么不用 `argparse`：这是一个
probe（探针/调试）脚本，参数只有三四个，`argparse` 生成的帮助信息和错误处理反而喧宾
夺主，增加不必要的复杂度。

### 5.4 `main()` 完整流程

1. **解析位置参数**：从 `sys.argv[1:]` 里剔除所有 `--` 开头的 flag 及其消费掉的值，
   剩下的是位置参数：
   - `positional[0]`（若存在）→ `max_steps`，默认 `12`；
   - `positional[1]`（若存在）→ `goal`，默认 `"探索周围环境，向北走出真新镇"`；
   - `positional[2:]` 中出现字面量 `"watch"` → `watch=True`。
2. **解析关键字 flag**（均经 `_flag()`）：
   - `--vision`（默认 `qwen3-vl-plus`）→ `vision_model`
   - `--text`（默认 `qwen-plus`）→ `text_model`
   - `--grid`（默认 `"on"`，等于 `"on"` 时 `grid=True`）
   - `--judge`（默认空串，空表示与决策同型号）→ `judge_model`
   - `--max-tokens`（默认 `"25600"`）→ `max_tokens`（int）。注释强调"上限不是预算"：
     只有模型自己想说这么多时才会真的花掉；若被 API 拒绝（各家对 `max_tokens` 有硬
     上限），应调低这个数。
   - `--state`（默认 `STATE`）→ `state_flag`；值为字面量 `"none"` 时 `state=None`，
     否则 `state=state_flag`。注释解释为何要用 `"none"` 而非空串表达"不要存档"：
     空串会和"这个 flag 根本没写"分不开，而这两种情况的结果差着一整段开场动画。
3. **早失败校验**：若 `state is not None` 且对应文件不存在，`raise SystemExit`
   直接报错退出。注释强调这是"早失败"的设计：路径打错时 PyBoy 可能静默从头跑，或者
   在几十行初始化日志之后才报错，两种情况都会浪费一整局才发现起点错误。
4. **构造 `Task`**（`pokemon_agent.schemas.task.Task`）：
   - `task_id`：默认由 `--task-id` 指定；若未指定，则从 `goal` 文本派生
     （`f"t{hashlib.sha256(goal.encode()).hexdigest()[:8]}"`），保证同一目标文本
     在跨进程运行时得到稳定一致的 `task_id`。注释强调 `task_id` **不能写死**：
     它是成功率的分组键，写死会导致命令行换了目标后新数据被错误聚合进旧任务。
   - `goal`：即目标文本。
   - `success_criteria`：默认为 `--criteria` 指定的同义反复式判据
     （`"画面上出现能直接证明这个目标已达成的证据"`）。注释指出这个默认判据只够
     跑通链路；真做实验必须用 `--criteria` 给出"只看一帧就能判真假"的具体判据，
     否则判定器只能凭"看起来差不多了"作答，成功率不可信。
   - `max_steps`：即上面解析出的步数上限。
5. **生成 id**：
   - `run_id = datetime.now().strftime("%m%d-%H%M%S")`（一次进程调用对应一个
     时间戳形式的 run_id）；
   - `episode_id = f"{run_id}-ep0"`（`run_id` + 序号，全局唯一）；
   - `event_id` 由 trace 内部分配的全局自增整数（不在本脚本生成）。
6. **调用 `build_real()` 装配**：

   ```python
   harness, trace, world = build_real(
       ROM, state,
       vision_model=vision_model, text_model=text_model,
       judge_model=judge_model, grid=grid, max_tokens=max_tokens,
       watch=watch, trace=LocalTrace(run_id=run_id, sse_sink=browser.publish),
   )
   ```

   关键点：传入的 `trace` 就是 `LocalTrace(run_id=run_id, sse_sink=...)` 本身——**不再需要外面
   包一层 `EchoTrace`**。`LocalTrace.append()` 落盘之后会自动调 `self.sse(event)`，
   `sse()` 就是（原来 `EchoTrace` 那套）控制台打印逻辑本身，既保留内存事件存储
   能力，又自带实时控制台打印，一个对象两件事都做。
   注释重申"实时打印挂在 trace 上，不往图节点里塞 print：实时观测和事后 replay
   看的是同一份数据，不会出现只有控制台有的信息"。
7. **打印运行头信息**：目标（task）、判据（criteria）、episode id、三个模型名与
   grid 开关状态、`max_tokens`、步数上限、存档路径（或"从 ROM 开头"）、
   无头/有窗口状态。注释强调**模型必须打出来**：换模型对比实验时，若日志不写型号，
   两份输出摆在一起就分不清哪份是哪个模型跑出来的，而这正是做对比实验的全部目的。
8. **运行 episode**：

   ```python
   try:
       outcome = harness.run(episode_id, task)
       print(f"\n结果      success={outcome.success}  steps={outcome.steps}  "
             f"reason={outcome.reason}")
   except AgentError as e:
       print(f"\n提前终止：{type(e).__name__}: {e}")
   finally:
       world.stop()
   ```

   `AgentError` 家族统一捕获、打印类型名与消息；无论成功/失败/异常，`finally` 里
   都会调用 `world.stop()` 释放 PyBoy 进程级资源。
9. **调用 `_summary(trace.all_events())`** 打印汇总统计（见下节）。

### 5.5 `_summary()` —— 从 trace 事件里统计三类调用的 token 消耗

```python
def _summary(events: list) -> None:
```

模块内注释交代了这段代码存在的历史教训：早前版本是照着旧 schema 写的
（用 `payload["source"]`、`EventType.COST`、`prompt_tokens` 这类已废弃的字段/类型），
schema 升级后这段代码没跟着改，结果是**跑完一整局才在最后一行崩掉**——彼时十几次
模型调用的钱已经花完了。教训归纳为一条原则：汇总必须按"信封字段"（`e.source` /
`e.type`，即 `TraceEvent` 顶层的结构化字段）读取，因为这是契约的一部分，稳定；而
`payload` 内部的键是各事件类型自己私有的东西，最容易漂移、改名。

具体统计逻辑：

1. **筛出所有模型调用事件**：`calls = [e for e in events if e.type is EventType.MODEL_CALL]`。
2. **按 `Source` 三分统计感知/决策/判定**：

   ```python
   for src, label in ((Source.PERCEPTION, "perception"),
                      (Source.DECISION, "decision"),
                      (Source.JUDGE, "judge")):
       rows = [e for e in calls if e.source is src]
       ...
       n_in = sum(int(e.payload.get("input_tokens", 0)) for e in rows)
       n_out = sum(int(e.payload.get("output_tokens", 0)) for e in rows)
       lat = [int(e.payload["latency_ms"]) for e in rows if "latency_ms" in e.payload]
       failed = sum(1 for e in rows if e.payload.get("ok") != "True")
       print(f"{label:<12} {len(rows):>3} 次（失败 {failed}）  "
             f"in={n_in:<7} out={n_out:<6} 平均 {sum(lat) // max(len(lat), 1)} ms")
   ```

   对每个来源（perception / decision / judge）分别打印：调用次数、失败次数、输入
   token 总量、输出 token 总量、平均延迟（毫秒）。**失败调用同样计入 token 统计**，
   注释解释：失败的调用同样烧了钱，单独报"失败"这一列，是因为只看总调用数会误以为
   每次调用都有产出。
   循环结束后曾经打印一行"↑ perception 含细看"——细看整条链路已经删除，
   现在 perception 这一类就是每步一次的感知（**动作链只在链尾感知一次**，
   所以一步一次，不再随按键次数翻倍）。

3. **动作类型统计**：

   ```python
   pressed = sum(1 for e in events if e.type is EventType.ACT)
   looked = sum(1 for e in events if e.type is EventType.INSPECT)
   pushed = sum(1 for e in events if e.type is EventType.GOAL_PUSH)
   pops = [e.payload.get("reason", "?") for e in events if e.type is EventType.GOAL_POP]
   print(f"动作         按键 {pressed} · 细看 {looked} · 拆子目标 {pushed}"
         f"（完成 {pops.count('done')} / 作废 {pops.count('superseded')}）")
   ```

   （**细看和拆子目标这两类现在都不产生事件了**：`INSPECT` 整条链路已删除，
   `GOAL_PUSH` 随 intent 分派一起删了，目标栈恒为一层。这段统计代码所属的旧入口
   也已搬走，留在这里是因为下面那句判断以后重做拆解机制时还用得上。）
   统计三类动作：按键（`ACT`）、细看（`INSPECT`）、拆子目标（`GOAL_PUSH`），并进一步
   统计子目标出栈（`GOAL_POP`）的原因分布——`done`（完成）与 `superseded`（因父目标
   已先完成而作废）。注释指出这是"目标栈和细看这两个机制唯一的直接证据"：拆十条弹
   十条表面上很好看，但如果其中八条是 `superseded`，说明模型在乱拆子目标而不是在
   真正规划。

4. **失败模式统计**：

   ```python
   errors: dict[str, int] = {}
   for e in events:
       if e.type is EventType.ERROR:
           errors[e.payload.get("kind", "?")] = errors.get(e.payload.get("kind", "?"), 0) + 1
   if errors:
       print("失败模式     " + "  ".join(f"{k}×{v}" for k, v in sorted(errors.items())))
   print(f"事件         {len(events)} 条")
   ```

   遍历所有 `EventType.ERROR` 事件，按 `payload["kind"]`（失败类型名，对应
   `errors.py` 中各异常类）分类计数，排序后打印，最后打印事件总条数。

---

## 6. 控制台打印：曾经的 `EchoTrace` 装饰器，现在是 `LocalTrace.sse()`

> **本节描述的类已删除。** `probe/echo_trace.py`/`EchoTrace` 不再存在——下面
> 6.1-6.5 节里的设计取舍、排版细节、辅助方法，**内容本身仍然准确**，但现在全部
> 是 `pokemon_agent/trace/store.py` 里 `LocalTrace.sse()` 方法的一部分，不再是一个
> 独立的、包住 `TracePort` 的装饰器类。差异只有两点，其余原样保留供理解排版逻辑：
>
> 1. **不再是装饰器**：`EchoTrace.__init__(self, inner: TracePort)` 那种"包住任意
>    `TracePort` 实现"的结构已经不存在——`LocalTrace` 自己既存储又打印，
>    `append()` 落盘后直接 `self.sse(event)`，不经过 `self._inner.append()` 这一层
>    转发。原因见 `interfaces/SPEC.md` 第 4 节："`sse` 是推，`append`/`replay` 是
>    拉，三者是同一个 `TracePort` 的三个方法"——协议本身有了推流的位置，不再需要
>    外部装饰器来补这个洞。
> 2. **方法名与触发点变了**：原来的 `EchoTrace.append()`（转发 + 打印）拆成了
>    `LocalTrace.append()`（只管落盘 + 分配 `event_id` + 调 `sse()`）和
>    `LocalTrace.sse(event: TraceEvent)`（只管把一条已经写好的事件呈现出来）——
>    下文提到的 `_echo()` 现在就是 `sse()` 本身，不再是一个被 `append()` 调用的
>    私有辅助方法。`__getattr__` 透传这层也不需要了：没有内外两层对象，
>    `run_episode.py` 里的 `trace.all_events()`/`trace.count()` 直接调
>    `LocalTrace` 自己的方法。

### 6.1 定位与设计取舍（历史记录，见上方说明）

`EchoTrace` 是包住任意 `TracePort` 实现的**装饰器**（不是替代品）：真实（或被包住的）
trace 实现照常收到全部事件，打印只是"旁路"附加行为。

挂点选在 trace 层而非在图节点（如 `Harness`/`Brain` 内部逻辑）里塞 `print`，源码给出
两条理由：

1. trace 本来就是事件流，选择在这里挂载打印，能保证**实时观测和事后 replay 看到的是
   同一份数据**。如果在节点里另加 `print`，就产生了第二份"只有控制台看得到"的信息，
   两边迟早会对不上（字段漂移、遗漏更新等）。
2. 这个设计本身演示了项目的分层原则：换一个 trace 实现 = 换观测方式，上层（`Harness`
   / `Brain` 等）代码一行都不用动。真正的 SSE 观测台（规划中的"阶段 2"）也会挂在
   同一个点上，只是把 `print` 换成向外推流。

### 6.2 如何包装任意 `TracePort`

```python
class EchoTrace:
    def __init__(self, inner: TracePort) -> None:
        self._inner = inner
        self._step_shown: tuple[str, int] | None = None

    def append(self, episode_id, step, type, source, payload=None) -> int:
        event_id = self._inner.append(episode_id, step, type, source, payload)
        self._echo(episode_id, event_id, step, type, source, payload or {})
        return event_id

    def replay(self, episode_id: str, after_event_id: int = -1) -> Iterable[TraceEvent]:
        return self._inner.replay(episode_id, after_event_id)

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)
```

- `append()`：先把事件转发给内层 `_inner.append()` 拿到真正分配的 `event_id`，
  再调用 `self._echo(...)` 打印，最后把 `event_id` 原样返回——对调用方完全透明。
- `replay()`：直接转发给内层，不做任何额外处理（回放不需要重新打印）。
- `__getattr__`：对未显式定义的方法（如 `LocalTrace` 契约之外的 `all_events()` /
  `count()`）做透传，使得 `EchoTrace` 包住 `LocalTrace` 之后，外部代码（例如
  `run_episode.py` 里的 `trace.all_events()`）仍能正常调用这些调试方法。

在 `run_episode.py` 中，实际构造方式是：

```python
trace=EchoTrace(LocalTrace(run_id=run_id))
```

即"内层负责存储、外层负责打印"的组合模式。

### 6.3 排版细节：`_step_shown` 与表头打印时机

```python
self._step_shown: tuple[str, int] | None = None
```

用于记录"这一步的表头（`step N`）打过没有"。docstring 解释了一个容易踩的坑：不能
把表头挂在 `OBSERVE` 事件上触发，因为事件流里 `model_call(perception)`（感知调用）
在因果顺序上先于 `OBSERVE`（先有感知调用，才产出观测结果），若表头挂在 `OBSERVE`
上，就会打印在本步的成本行**下面**，读日志的人会误把那一行成本读成上一步的。
因此该排版问题在 `EchoTrace` 内部通过 `step` 值变化来触发表头打印，而**不去改动
事件流本身**——因为"trace 是唯一的事实来源"，打印层的排版需求不应该反向影响
数据模型。

`LABEL_W = 15`：标签列宽常量，由最长的标签 `perception_cost` 决定。写成命名常量而非
散落在各处的字面量宽度（如 `:<9`），是因为一旦对齐不一致，多行的 `thought` 文本
就会和单行的 `action` 错开，"读日志的人第一眼看到的是排版乱，而不是内容"。

`COST_LABEL`：`Source` → 标签字符串的映射（`PERCEPTION → "perception_cost"`，
`DECISION → "decision_cost"`，`JUDGE → "judge_cost"`）。标签**要带 `_cost` 后缀**：
这一行报的是"这次调用花了多少"（token、延迟），不是"感知到了什么"；若只写
`perception` 会和另一处的 `observe` 标签混成一件事，而账单和内容是两回事。

### 6.4 辅助方法

- `_facts(p)`：把 `payload["facts"]`（JSON 字符串）解析成 dict，解析失败时返回空
  dict（容错，不抛异常）。
- `_wrapped(label, text)`：整段打印，**不截断**、**保留原有换行**。理由：
  `thought` / `remember` / `ERROR` 都是这一步的实质内容，截断等于把最该看的部分
  切掉。实现上"先按原有换行拆分，再对每一行分别做折行（`textwrap.wrap`，宽度 88）"，
  而不是直接对整段文本调用 `textwrap.wrap`。注释举了一个真实教训：早一版直接
  `textwrap.wrap(text)`，会把原有换行当作普通空白吃掉，于是 `remember` 里一张
  10×9 的 `walk_map`（走过的地图记录，多行文本表示）被压成一条横着的长字符串，
  正好破坏了这一步最需要看清楚的信息。
**`_times(p)` 已经删除。** 它从 `args` 的 JSON 里抠 `times` 格式化成 `×N`，
并刻意区分"模型明确给了 1"和"模型压根没给 times"（两者表现相同、修法完全不同：
前者调 prompt 措辞，后者排查渲染链路有没有把这个能力告诉模型）。那个区分现在
不需要了——次数是 `ActionSegment.times`（1-8），**解析期就校验**，缺失或越界走
`ParseFailure` 并自带一条 error 事件，根本到不了打印这一层。
它退场前还留下一个教训：动作链上线后 `args` 变成了段数组，而 `"times" not in args`
对一个 list 恒成立，于是控制台**每一行 act 都印 `[无 times]`**——
**一个恒真的提示比没有提示更糟**，它看起来像信息。

### 6.5 `sse()`：终端只打四类，其余七类交给观测台

`sse()` 一进来先把事件交给 `_sse_sink`（观测台的 `publish`），然后才决定终端要不要打印。
**`BROWSER_ONLY` 这个集合是唯一的事实来源**：

```python
BROWSER_ONLY = frozenset({
    EventType.OBSERVE, EventType.MEMORY_READ, EventType.THINK,
    EventType.ACT, EventType.INSPECT, EventType.MEMORY_WRITE,
    EventType.OBJECT_NOTE,
})
```

分工是有意的：**终端回答"跑得对不对"**——账单、错误、目标出栈、episode 起止，
一屏能扫完；**观测台回答"它当时看到了什么、想了什么"**——观测、记忆、推理、动作，
那些内容一条就是十几行，混在终端里会把前一类冲掉。

这个 `return` 放在**表头之前**：只有观测台事件的那一步，终端不该冒出一个空的
`----- STEP n -----`。

终端实际打印的四类：

- **`EPISODE_START`** / **`EPISODE_END`**：分隔线 + 一行汇总（`success` / `steps` /
  `reason`），`END` 再用 `_wrapped("why", ...)` 打印判定理由原文。
- **`MODEL_CALL`**：按 `COST_LABEL` 取标签（`perception_cost` / `decision_cost` /
  `judge_cost`），打印 `in` / `out` token、`latency`、`attempt`、`ok`，判定多打一个 `depth`
  ——`depth` 必须标出，否则满屏 judge 行分不清哪次决定整局成败、哪次只是子目标弹栈。
- **`GOAL_POP`**：`depth` / `reason` / `goal`，外加 `_wrapped("why", ...)`。
- **`ERROR`**：`kind` / `attempt` + `_wrapped("reason", ...)`。

**这里曾经是一句裸的提前 `return` 加下面一大片永远执行不到的分支。** OBSERVE /
MEMORY_READ / THINK / ACT / INSPECT / MEMORY_WRITE / OBJECT_NOTE 七类的完整打印代码
（`observe` 的 facts 逐条缩进、`recall` 行、`thought` 原文、`act` 行、细看的提问与回答、
`remember` 行）都还留在文件里，**但一行都不会执行**。死代码在这里的代价不是几十行，
是**读代码的人对整个文件的信任**：改了那些分支、跑一遍、终端毫无变化，只能怀疑是
自己改错了。现在那些分支删掉了，名单换成上面这个集合——要让某一类回到终端，
从集合里删掉它，再去写它的打印分支。

那几个分支里值得留下的判断：

- `ACT` **不该打印 message**：`ToolResult.message` 的内容就是执行后的新 `status`，
  和下一条 `OBSERVE` 完全重复。这个判断后来走到了尽头——**`message` 字段本身删掉了**，
  因为除了这条复读没有任何消费方（详见 `schemas/SPEC.md` 的 `ToolResult` 一节）。
- `MEMORY_WRITE` 不把 `ref` 前置在标签里：`StepMemory.render()` 自己开头就是那个坐标，
  再拼一次会变成 `(ep, 2) (ep, 2) 当时看到…`。
- `OBSERVE` 的多行值（如 `walk_map`）要按行缩进对齐整体打印，不能挤成一行——
  这条现在活在观测台的渲染里（`browser.py` 把 `walk_map` 按 `\n` 拆开逐行输出）。

- **`ERROR`**：用 `_wrapped("ERROR", reason)` 打印失败原因原文。

---

## 7. 从命令行到真实跑一局的完整调用链

```
用户在命令行执行
    python -m probe.run_episode 30 "…" watch --state assets/route1.state --task-id t_route1
        │
        ▼
probe/run_episode.py : main()
    │  1. _flag() / 位置参数解析出 max_steps / goal / watch / vision_model /
    │     text_model / judge_model / grid / max_tokens / state / task_id
    │  2. 早失败校验：--state 指向的文件必须存在
    │  3. 构造 Task（task_id 从 goal 的 sha256 派生或用 --task-id 覆盖，
    │     success_criteria 默认同义反复，需 --criteria 给出可判定的真实判据）
    │  4. 生成 run_id（时间戳）、episode_id（run_id + "-ep0"）
    │
    ▼
pokemon_agent/build.py : build_real(ROM, state, vision_model=..., text_model=...,
                                     judge_model=..., grid=..., max_tokens=...,
                                     watch=..., trace=LocalTrace(run_id=run_id))
    │  —— 全项目唯一的具体实现装配点 ——
    │  · QwenVision(model=vision_model, preprocess=(GridOverlay(),) if grid else ())
    │  · PyBoyWorld(rom, vision, state_path=state, watch=watch)
    │  · trace = 传入的 LocalTrace(...)（自带内存存储 + sse() 控制台打印，不再需要
    │    外面套 EchoTrace——该类已删除，见第 4、6 节）
    │  · GameTools(world) —— 只碰 world
    │  · MemoryTool() —— 独立的语义记忆
    │  · Brain(decide_llm=QwenText(text_model,...), judge_llm=QwenText(judge_model or text_model,...))
    │  · 返回 Harness(game, memory, brain, trace), trace, world
    │
    ▼
probe/run_episode.py : main()（续）
    │  5. 打印运行头信息（task / criteria / episode / 三个模型名 / grid / max_tokens /
    │     步数限制 / 存档 / 无头或窗口）
    │
    ▼
Harness.run(episode_id, task)
    │  —— 控制循环，本次未读其源码，但从 build.py 的依赖图可知它驱动：
    │     GameToolPort → WorldPort → PyBoyWorld → VisionProvider（感知）
    │     MemoryToolPort → memory/（记忆读写）
    │     BrainPort → LLMProvider（决策 / 判定）
    │     TracePort（事件写入）
    │  · 每一次 append() 调用：LocalTrace.append()（分配 event_id、校验单调性、
    │        存入内存 list）→ 落盘后自动调 self.sse(event) → sse() 按 EventType
    │        分支实时格式化打印到控制台（OBSERVE / THINK / MODEL_CALL / GOAL_PUSH /
    │        GOAL_POP / INSPECT / MEMORY_WRITE / ERROR / EPISODE_START/END 等）——
    │        payload 的组装不在这里，`Harness` 调用点上是先经过 `trace_utils.xxx()`
    │        拼好 `AppendArgs` 再 `self._trace.append(*args)`，`LocalTrace` 本身
    │        不认识任何领域对象（见 `interfaces/SPEC.md` 第 4 节）
    │
    ▼
main() 收尾
    │  6. try/except AgentError：正常结束打印 success/steps/reason；
    │     若中途抛出 errors.py 中定义的任一 AgentError 子类，打印
    │     "提前终止：{类型名}: {消息}"
    │  7. finally: world.stop()（释放 PyBoy 进程级资源，谁开的谁关）
    │  8. _summary(trace.all_events())
    │       —— trace 就是 LocalTrace 本身，直接调 all_events() 取出完整事件列表
    │          （不再有 EchoTrace 那层 __getattr__ 透传）
    │       —— 按 e.type / e.source（信封字段，而非 payload 内部键）统计：
    │            · perception / decision / judge 三类 MODEL_CALL 各自的
    │              调用次数、失败次数、input/output token 总量、平均延迟
    │            · ACT / INSPECT / GOAL_PUSH 三类动作次数，以及
    │              GOAL_POP 的 done / superseded 分布
    │            · 按 payload["kind"] 分类统计 ERROR 事件（失败模式分布）
    │            · 打印事件总条数
```

**关键衔接点小结**：

- `probe/run_episode.py` 是唯一的命令行入口，它不认识任何具体 provider 类型，
  只调用 `build.py` 暴露的 `build_real()`。
- `build.py` 是唯一知道 `QwenText` / `QwenVision` / `PyBoyWorld` / `GridOverlay`
  等具体实现的地方；它把 trace 参数做成可注入的（`trace: TracePort | None`），
  使 `run_episode.py` 能够直接传入 `LocalTrace(run_id=run_id)`——存储和打印现在是
  同一个对象的两件事（`append()` 落盘后自动 `sse()`），不再是"内层存储 + 外层
  装饰器打印"的组合，`build_real()` 内部逻辑同样不需要知道 trace 具体怎么实现。
- `errors.py` 中的 `AgentError` 家族是 `Harness`/`Brain` 与 `run_episode.py` 之间
  的失败契约：`run_episode.py` 只需要认识基类 `AgentError` 就能安全兜住所有预期内
  的失败，同时通过 `type(e).__name__` 保留具体失败类型用于打印。
- `experiment/manifest.py`（`RunManifest`）定义了实验可复现性记录的模型，但在
  当前读到的调用链（`run_episode.py` → `build_real()`）中**尚未被实际调用**——
  它是为落盘/replay 等"阶段 2"能力预先搭好的骨架，目前独立存在。
- `trace/store.py`（`LocalTrace`）是当前唯一可用的 trace 实现：满足 `TracePort`
  契约（`append`/`replay`/`sse`），只存内存，`sse()` 自带实时控制台打印——曾经
  拆在两个文件、两层对象里的 `mock_trace.py`（存储）+ `echo_trace.py`（打印装饰器
  `EchoTrace`）已经合并；`run_episode.py` 里现在显式写出的是
  `LocalTrace(run_id=run_id)`，不再是 `EchoTrace(LocalTrace(run_id=run_id))`。
  `trace/utils.py`（`trace_utils`）是这次拆分额外长出来的第三块：一批不认识
  `TracePort` 的纯函数，专管"把领域对象翻译成 `append()` 的参数"，`Harness` 是
  唯一调用它们的地方（详见 `interfaces/SPEC.md` 第 4 节、`harness/SPEC.md`）。

---

*本文档所有结论均来自对上述源文件（含中文注释）的直接阅读，未对源码之外的行为
做推测性描述；涉及"未在本次阅读范围内验证"的内容（如各 `AgentError` 子类的具体抛出
点）已在正文中明确标注。第 4、6 节及本节已依据 `pokemon_agent/trace/` 包的当前
实现（`LocalTrace.sse()` 取代 `EchoTrace`）更新，其余章节未受这次改动影响。*
