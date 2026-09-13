# Pokemon_Agent —— 开发规范

> 本文件是项目的硬约束。写代码前先读这里，规范与代码冲突时改代码，不改规范（要改规范先讨论）。

## 一、项目是什么

用一套通用 harness（脚手架）驱动一个**无状态大脑**去玩通神奇宝贝，验证「结构化 episodic 记忆
+ 状态表在线归并 + 蒙特卡洛信用分配」在长程任务里的价值。**全程不更新任何模型权重。**

设计文档在 Obsidian：`AI Infra/Harness-Engineering/Projects/项目B-Harness驱动神奇宝贝Agent设计文档.md`。
代码与文档冲突时，以文档的架构约束为准，实现细节以代码为准。

**当前阶段：原型已接上真实模拟器与真实模型。** 大脑的 ReAct 循环、语义记忆、
独立判定器都在真实环境里跑；状态表在线归并（机制一）与 MC 回填（机制三）仍未做（见第十一节）。

## 二、铁律（违反即返工，不接受"先这样以后再改"）

1. **大脑不持有任何状态。** `brain/` 下的代码不许有跨步骤的实例变量、不许有模块级可变全局。
   每一步的全部输入都来自参数，全部记忆都来自工具调用。
   *为什么*：大脑无状态是整个架构的地基，一旦漏了状态，harness 的 trace / replay / checkpoint 全部失真。

2. **`brain` / `memory` / `trace` / `world` 是四个独立第三方模块，各自只暴露一个 Port。**
   `brain/` 不许 import `harness/`、`world/`、`memory/` 的任何东西——它只依赖**自己声明的
   provider 契约**（`brain/interface/llm_provider.py` 的 `LLMProvider` / `JudgeProvider`）
   与 `errors/`。跨模块的数据交换**只能发生在 tool 层**。
   依赖方向永远是：模块只认自己的 Port，`tools/*_tool.py` 认识两边的形状并做转换。
   **协议的归属看"谁消费"不看"谁实现"，实现也跟着协议走**——`providers/` 这个包 0913
   已解散：`QwenProvider`/`ArkProvider`/`DeepSeekProvider` 进 `brain/providers.py`，
   `FastEmbedText`/`FastEmbedReranker` 进 `memory/`。
   **"谁依赖 brain"只有唯一答案：tool 层（0913 深夜九审计定案）。** 全仓库对
   `brain` 的**实现依赖**（`Brain`/`BrainPort`/`BrainLlmConfig`/`build_llm_providers`/
   厂商类）现在只剩 `tools/` 五处；装配点 `build.py` 对 brain **零 import**——
   它要的两样东西都经 tool 层的接线工厂拿：`BrainTool.build(text=…)` 造大脑、
   `build_vision_provider(model=…)` 造 world 的感知 provider。装配只递型号名，
   `BrainLlmConfig` 由 `BrainTool.build()` 内部构造。
   （`harness`/`schemas`/`api`/`world` 对 brain 的引用一律是**数据形状**
   （`Action`/`Goal`/`Task`/`RunPlan`/`Reflection`/`EpisodeSummary`/
   `StepVerifyVerdict`/五个结果袋），不是实现依赖，见第十二节第 4 条。）
   *为什么*：这条一旦破，"换一个世界 / 换一种记忆存储"就要改大脑代码，模块能整体拷走
   复用的意义就没了。

3. **模块层的 Port 收裸字段，不认识本项目的 `*Req` 信封。** 信封是"某一跳"的概念
   （harness → tool 那一跳有自己的信封），不属于模块层。参照 `MemoryStorePort`：
   入参是 `str` / `Sequence[str]` / 少数参与逻辑运算的关键结构（`keys` / `entries` / `images`）。
   *为什么*：信封一旦进模块层，模块就被这个项目的编排方式绑死了。

4. **mock 与真实实现必须实现同一个 Protocol。** 不许出现"mock 多一个方法"或"mock 签名不一样"。
   *为什么*：mock 的唯一价值是能被无痛替换。

5. **跨层传递的数据一律是 Pydantic 模型，不用裸 dict。**
   *为什么*：接口边界靠类型说话；后面接约束解码时 schema 直接复用。

6. **每一步都必须产出 trace 事件。** 没有 trace 的执行路径视为未完成。
   *为什么*：trace 是 replay、checkpoint、成本统计的共同底座，后补代价极高。

## 三、可读性与可维护性（和铁律同等强制）

### 1. 变更日志 —— 每次改动都要留痕

根目录维护 `CHANGELOG.md`。**每一次动代码都追加一条**，倒序排列（最新在最上）。格式：

```
## 2026-08-13 —— 搭起 ReAct 最小闭环
**改了什么**：新增 brain/react.py，graph/build.py 用 StateGraph 装配三节点循环。
**为什么这么改**：ReAct 的 think/act/observe 三段正好对应三个节点，
用图表达比 while 循环更容易在后面插入 masking 和记忆检索节点。
**取舍**：暂时没做并发工具调用——串行更好调试，且当前动作之间本来就有顺序依赖。
**影响面**：新增，不动已有接口。
```

四段固定：**改了什么 / 为什么这么改 / 取舍 / 影响面**。
「为什么」写不出来的改动，说明这个改动没想清楚，先别写。
*注意*：这是给人读的决策记录，不是 git log 的复制品——不要写"修改了第 42 行"这种。

### 2. 接口先行 —— 先写接口类，再写实现

- 每个模块的对外能力**先在 `interfaces/` 里写成 `Protocol`（或 ABC）**，带完整类型注解和 docstring，
  再去写实现。接口文件本身就应该是可读的设计文档：**光读 `interfaces/` 就能看懂整个系统怎么运转。**
- 接口的 docstring 要写清楚三件事：**这个方法承诺什么、什么情况下会失败、调用方要保证什么前置条件。**
- 用 `Protocol` 而不是继承基类，除非需要共享实现。
  *为什么*：Protocol 是结构化类型，mock 不需要显式继承就能替换，测试里最省事。
- 一个接口方法数量超过 6 个就该拆——说明它承担了多个职责。

### 3. 依赖注入 —— 不许自己 new 依赖

- 组件的依赖**一律从构造函数传入**，类型标成接口而非具体实现：

```python
class Brain:
    def __init__(self, decide_llm: LLMProvider, judge_llm: LLMProvider,
                 tools: ToolPort, trace: TracePort) -> None:
```

- **禁止**：在类内部 `import` 并实例化依赖、模块级单例、读全局配置。
- 组装只发生在**一个地方**（`build.py` 的装配函数），
  其余代码不许知道具体用的是 mock 还是真实实现。
  *为什么*：这是"mock 能无痛换真实实现"的机械保证，比铁律 3 更进一步——铁律管签名一致，
  依赖注入管调用方根本不知道自己拿的是谁。

### 4. 用 assert 表达契约：precondition 与 postcondition

**assert 是可执行的文档。** 它声明"这里必须成立"，让读代码的人知道这个函数假设了什么、
承诺了什么，并在开发期让违约就地爆炸。它**不参与程序的正常语义**。

契约三件套，都用 assert：

| | 是什么 | 谁的责任 | 位置 |
|---|---|---|---|
| **precondition** | 调用方必须保证的 | 调用方违约 = 调用方的 bug | 函数入口 |
| **postcondition** | 本函数向调用方承诺的 | 不成立 = 本函数的 bug | 函数出口 |
| **invariant** | 对象在方法之间始终成立的 | 不成立 = 类的 bug | 方法出入口 / 专门的 `_check_invariant()` |

接口 docstring 里写的「调用方要保证什么 / 本方法承诺什么」，就是这里要 assert 的东西——
**docstring 说明契约，assert 执行契约**，一一对应。

```python
def choose(self, obs: Observation, space: ActionSpace) -> Action:
    """选出下一步动作。

    前置条件：space 非空（调用方保证；空动作空间是 harness 的 bug，不是大脑要处理的情况）。
    后置条件：返回的动作一定属于 space。
    """
    assert space.names, "choose() got an empty action space"

    action = self._parse(self._llm.complete(self._prompt(obs, space)))

    assert action.name in space.names, f"brain returned {action.name!r} outside action space"
    return action
```

> postcondition 比测试更值钱：测试只覆盖你想到的用例，出口 assert 覆盖**所有实际执行**。
> 上面这条出口 assert 就是"大脑不会幻觉出不存在的动作"这个核心主张的运行时证据。

#### assert 不做流程控制、不做兜底、不校验外部输入

判据只有一条：**`python -O` 会删掉所有 assert。删掉这行后程序行为若会改变（除了不再报错），
它就不该是 assert。**

```python
# ✗ 拿 assert 当 if 用，再 catch AssertionError 兜底
# ✗ 把程序必须执行的副作用塞进 assert：assert self._register_tool(tool)
# ✗ 校验会正常失败的外部输入：assert llm_output.startswith("{")
```

第三条尤其要守住：LLM 输出、模拟器返回、配置文件**不是"调用方"**，它们出错是
**预期内的运行时情况**，走 `ParseFailure` / `IllegalAction` 那套显式异常，并产出 trace 事件。
一旦 assert 里混进输入校验，读者就无法从 assert 判断哪些是我承诺的约束、
哪些只是防御性代码，它作为文档的价值就没了。

本项目的典型契约：`execute()` 入口断言动作在 action_space 内（pre）；
`choose()` 出口断言返回动作在 space 内（post）；写 trace 时断言 `event_id` 大于上一条（invariant）；
恢复 checkpoint 后断言 step 与事件序列长度一致（post）。

### 5. 测试是用法示范，不是覆盖率任务

测试的第一读者是**想知道这东西怎么用的人**（包括三个月后的你和面试官）。所以：

- **单元测试**：每个接口至少一个，展示"最简单的正确用法长什么样"。
- **集成测试**：至少一个端到端——`FakeLLM + MockWorld` 跑完整 episode，
  从装配到断言全部可见，**这个测试就是项目的使用说明书**。
- 测试要读起来像文档：Arrange / Act / Assert 三段用空行分开，
  测试函数名是一句话（`test_brain_never_picks_action_outside_space`）。
- **不追覆盖率、不测私有函数、不写 mock 套 mock 的测试。**
  测试难写说明依赖注入没做好，回去改设计而不是加 mock。

## 四、目录结构

```
pokemon_agent/
├── schemas/          Pydantic 数据模型（跨层契约）。记忆一族按**检索单元**命名：
│                     step_memory（一条=一步）/ episode_memory（一条=一整局）/
│                     object_fact（一条=一格）/ knowledge（不挂坐标的先验）/
│                     episode_summary_io（蒸馏那次调用的请求+响应，不是记忆）
│                     其余：Observation / Action / ActionSpace / TraceEvent / Completion。
│                     `harness/communication/ModelCall.py` 是**跨层信封**那份账
│                     （带 `with_attempt`；brain 方言另有一份，见 brain 条目）
├── brain/            纯决策层。**可整体拷走复用的第三方模块**——只依赖自己声明的
│                     两个 provider 契约与 errors，**不知道 harness / world / memory
│                     的存在**。对外只有 `interface/brain_port.py`（六方法裸字段契约）
│                     与 `interface/domain/`（brain 自己的方言：Action/Goal/Task/
│                     RunPlan/Reflection/EpisodeSummary/StepVerifyVerdict + 五个结果袋
│                     + `model_call.py` 那份**不带 `with_attempt`** 的账）
│                     + `interface/llm_config.py`（`BrainLlmConfig` 选型纯数据，
│                     0913 深夜九从工厂模块搬来——**只为数据而来的调用方不该连带进口
│                     厂商实现面**）。`providers.py` 是厂商实现本体、
│                     `build_llm_providers.py` 是接线工厂、`errors.py` 是内部词汇
│                     （自成一根 `BrainError`，不继承 `AgentError`——那些异常在
│                     tool 层的重试循环里就被吃掉、翻译了，走不到 harness）、
│                     `schemas/` 是 brain 自己的四封补全信封（0913 深夜十一从顶层
│                     `schemas/providers/` 搬来，provider 已全搬进来，这就是内部协议）。
│                     **`pokemon_agent.*` 外部依赖为零**：只剩标准库 + `pydantic` + `PIL`。
│                     这就是"可作为第三方整体拷走"的字面含义
├── harness/          控制循环本体（LangGraph 状态图），全项目唯一写 trace 的地方。
│                     **只依赖 tools / schemas / prompts 三层，不依赖 trace 的实现**
│                     （trace 也是独立模块，只通过 Port 说话）
├── world/            WorldPort 实现：PyBoy + 视觉模型的粘合层 + 世界语义常量
│                     （INTERACT_KEY / DIRECTION_KEYS——"这个世界怎么按键"的知识）
├── tools/            Harness 伸向各模块的手：game_tool / memory_tool / brain_tool /
│                     trace_tool。**跨模块的双向转换一律在这一层**——tool 认识两边的
│                     形状，是唯一的桥。prompts/ 也住这里（prompt 是 tool 的素材）
│                     **两个接线工厂也住这里（0913 深夜九）**：
│                     `BrainTool.build(text=…, judge=…)` 造大脑 + 四个 provider、
│                     `vision_factory.build_vision_provider(model=…)` 造 world 的
│                     感知 provider。**"谁依赖 brain"的唯一答案就是本层**——
│                     装配点 `build.py` 只递型号名，对 brain 零 import
├── memory/           memory 子系统整块（契约 + 实现 + 算法，可整体拷走复用）：
│                     ports.py 是对外契约（MemoryStorePort）；store.py 是统一记录
│                     存储（MemoryStore：一条记录一个 <uuid>.json/.md + 每文件夹
│                     倒排索引 index.json + 向量 sidecar vectors.jsonl）；
│                     retrieval.py 是混合检索纯函数（BM25 + embedding + RRF +
│                     reranker，只认字符串，不认记忆类型）；
│                     embedding_provider.py / reranker_provider.py 是本模块消费的
│                     两个协议。
│                     只做读写与索引，不做语义判定（见下方分层原则）
├── providers/        **0913 已解散**——实现按"谁消费"回了各自模块：
│                     `QwenProvider`/`ArkProvider`/`DeepSeekProvider` →
│                     `brain/providers.py`；`FastEmbedText`/`FastEmbedReranker`
│                     → `memory/fastembed_text.py` / `fastembed_reranker.py`。
│                     协议则更早各归其位：LLMProvider/JudgeProvider → brain.interface；
│                     VisionProvider → world.interface；
│                     Embedding/RerankerProvider → memory。
│                     **本目录不再存在。**
├── vision/           图像预处理（网格叠加、放大）
├── trace/            独立模块：TracePort 契约 + LocalTrace（落盘）+ 事件类型词表。
│                     它不是 harness 的内部件——harness 只经 TraceToolPort 说话
├── experiment/       实验任务定义（tasks.py）、experiment_states/（钉死存档）、
│                     real_check/（六维度真实链路核对）——仓库根级，不在包内
├── config.py         **全项目唯一的策略常量集中地**：重试预算 / 动作输出上限 /
│                     循环控制 / 召回与判定四组。判据——"改这个数是为了做实验还是
│                     为了让代码正确"：前者来 config，后者（帧数、内存地址、
│                     网关下界等模块私有物理量）留在各自模块
└── build.py          唯一的装配点（全项目唯一 new 具体实现的地方）

tests/
AGENTS.md          开发规范（本文件）
CHANGELOG.md       变更日志，每次改动追加
pyproject.toml
```

**分层原则（两条）：**

1. **memory 只保管 harness 交给它的数据结构与索引、按键原样读写**；"发生了什么、影响了谁"
   这类语义判定（交互判定、受影响对象计算）由 harness 完成后以数据的形式交给它
   ——memory 不理解游戏，只理解键和记录。
2. **`brain` / `memory` / `trace` / `world` 一律按"独立第三方模块"对待**：各自只对外暴露
   一个 Port（`BrainPort` / `MemoryStorePort` / `TracePort` / `WorldPort`），契约收裸字段，
   不认识本项目任何 `*Req` 信封（信封是"某一跳"的概念，只存在于 `schemas/harness/`）。
   模块之间**只经 tool 层交换数据**——`tools/*_tool.py` 认识两边的形状，双向转换只在那里做。
   允许**冗余类对象**（同一结构两边各声明一份、字段同构但互不引用），换来两边独立演进。
   *为什么*：这是"mock 能无痛换真实实现"和"模块能整体拷走复用"的机械保证。

一个模块超过 300 行就拆。一个函数超过 50 行就拆。

## 五、编排：LangGraph

- 循环用 `StateGraph` 承载，**不手写 while 循环**。
- `LoopState` 是唯一的图状态载体，必须是 Pydantic 模型或 TypedDict，字段有明确类型。
- 节点函数是纯函数形态：`(state) -> state 增量`，副作用只允许发生在工具调用节点。
- **LangGraph 只管循环调度与状态传递。** 记忆层、状态表、值回填一律自己实现，
  不用 LangChain 的 Memory / Agent / Tool 封装。
  *为什么*：这些是本项目的原创部分，套框架抽象会讲不清楚也调不动。

## 六、LLM 与输出格式

- 本阶段已有真实 provider，**各自住在消费它的模块里**（0913 起 `providers/` 包已解散）：
  `QwenProvider`（DashScope，语言+视觉两用）、`ArkProvider`（火山方舟/豆包，
  型号名必须带日期后缀）、`DeepSeekProvider`（DeepSeek 官方 API）住
  `brain/providers.py`；`FastEmbedText` / `FastEmbedReranker`（本地向量化与重排）
  住 `memory/`。它们通过四个 Protocol 接入：`LLMProvider` / `JudgeProvider`
  （`brain/interface`）、`VisionProvider`（`world/interface`）、
  `EmbeddingProvider` / `RerankerProvider`（`memory/`）。**brain 的四个 provider 由
  `brain/build_llm_providers.py` 的 `build_llm_providers(config)` +
  `BrainTool.build(text=…, judge=…, verify=…, plan=…, max_tokens=…)` 组装**
  ——哪个技能接哪家厂商是 brain 的接线知识；`BrainLlmConfig` 由
  `BrainTool.build()` 内部构造（0913 深夜九：签名收裸字段，装配点因此不必
  import 任何 brain 名字）。world 的感知 provider 同理走 tool 层的
  `build_vision_provider(model=…)`。装配点只递型号名。
  代码里**不许出现任何直连模型 SDK 的调用**——直连只发生在
  `brain/providers.py` 和 `memory/fastembed_*.py` 这几个实现文件里。
- **prompt 是规则，入参是素材——不互相替代，同一东西绝不两处传。** "怎么判、怎么想、
  怎么规划"全在 prompt 里（调用方组装、模块原样拿去问模型）；"判什么、想什么"才是入参。
  所以一个方法要么在 prompt 里给、要么当参数传，**不许两边都放**（论据、`history` 这些
  就是这样去掉的）。prompt 模板与组装函数住在 `tools/prompts/`——prompt 是 tool 的素材。
- 动作选择输出用 **Pydantic schema**（`Thought` / `Action` / `Args`）解析。
- **解析失败要重试并计数**，重试次数与失败计数进 trace。不许静默吞掉解析错误。
  重试循环住在 **tool 层**（`BrainTool.choose` / `BrainTool.plan`）——拼重试纠正说明是
  "拥有这次调用"的那层的事；账走 `resp.attempts`（成功）或异常携带的 `exc.calls`（耗尽）。
- 约束解码（constrained decoding）留到接真实模型时再上，现在不做。

## 七、代码风格

- Python 3.11（不是 3.10——`enum.StrEnum` 要 3.11 才有，`trace/interface/domain/trace_kind.py` 等用到）。所有公开函数、方法、Pydantic 字段**必须有类型注解**。
- `ruff` 管 lint + format，行宽 100。提交前跑 `ruff check . && ruff format .`。
- 命名用完整英文单词，不用缩写（`action_space` 不是 `act_sp`）。
- 注释仅三处：**文件顶层 docstring、函数顶层 docstring、函数内步骤进度**（`# 步骤 N：`）。
  注释只写契约与进度；取舍论证与历史叙事一律进 `CHANGELOG.md`（变更类）或
  `docs/spec/<模块>/SPEC.md`（设计类），不留在代码里。分节线（`# ---- x ----`）保留。
- 不写 README 除非明确要求；说明写在 AGENTS.md 或 docstring。

## 八、错误处理

- 不许裸 `except:` 或 `except Exception: pass`。
- 预期内的失败（LLM 解析失败、动作非法、工具超时）走**显式返回值 / 自定义异常**，
  并产出一条 trace 事件；预期外的异常直接向上抛，不要在中途吞。
- 每类失败要有名字（`ParseFailure` / `IllegalAction` / `ToolTimeout`），
  因为后面 replay 要按失败类型归类统计。

## 九、trace 约定（后面 checkpoint / replay 全靠它）

每条事件至少含：

| 字段 | 说明 |
|---|---|
| `event_id` | **单调递增整数**，replay 排序与断线补发靠它 |
| `episode_id` | 一次 episode 的标识 |
| `step` | 第几步 |
| `type` | 7 类（`pokemon_agent/schemas/datastore/__init__.py::EventType`，见 `docs/spec/DATAFLOW.md` 2.2）：`model_call` / `error` / `llm_outcome` / `view` / `act` / `memory_io` / `lifecycle`。**0903 收敛原则**：type 与生产者（source）正交、数量极小；原 20 类里"哪个节点/哪类产物"的语义全部降级为 `payload.kind`（如 llm_outcome=intent/verdict/audit、memory_io=read_*/write_*、lifecycle=run/episode 边界 + step）。`model_call`/`error` 是唯二天然跨 source 的纯种类，其余五个是承认领域本质单源的产物种类。`TRACE_SCHEMA_VERSION` 升到 3，v2 旧文件（type 值如 observe/think/retrieve…）不再可解析 |
| `payload` | 该类型的结构化内容 |
| `ts` | 时间戳 |

- trace 是**追加写的事件序列**，不是可变状态快照——但这说的是 trace 自身的写入
  方式，不是 checkpoint 的存储形态。checkpoint 存的是**状态快照 + 事件游标**
  （快照 = `RunState`/`EpisodeRunState` 整份 dump + 模拟器世界快照，游标指向
  trace 的 `event_id`/记忆的 `step` 用于对账），不是靠重放事件序列重建状态——
  模拟器世界与已花的模型调用成本都不可能从事件重建。详见
  `docs/spec/harness/PLAN_checkpoint.md` §3.2、`docs/ROADMAP.md` 第 16 条。
- 本阶段 `LocalTrace`（落盘 JSONL）就够，但接口按"能落盘、能重放"设计。

## 十、测试

规则见「可读性与可维护性 / 5. 测试是用法示范」。工具与硬性要求：

- `pytest`。测试文件与被测模块同名：`tests/test_<module>.py`。
- 必须存在的两个：**FakeLLM 跑完整 ReAct 循环且结果确定可复现**；
  **大脑在给定观测下选出预期动作**。
- 测试不许连网、不许调真实模型、不许依赖时间戳精确值。

## 十一、这个阶段明确不做

状态表在线归并（机制一）、MC 回填（机制三）、skill library（机制二）、沙箱。

**别提前做。** 但接口要留得住：设计任何抽象时问一句"机制一接进来时这里要改吗"，
要改就说明抽象错了。

## 十二、schemas：信封与接口模型命名（2026-09-10 定稿）

**分包形态**：七个产出模块各自一个包、各自一个统一出口（`frontend` / `harness` /
`world` / `memory` / `trace`）。**schemas 侧不再有 `providers` 子包**——它 0913 深夜十一
随代码层 `pokemon_agent/providers/` 一起解散：四封信（`LlmComplete*`/`VisionDescribe*`）
已是 **brain 的内部协议**，随 provider 搬进 `brain/schemas/`；world 另有一份自己的
`VisionDescribe*` 副本（`world/interface/domain/vision_describe.py`）。包内按种类落到
`communication/` `domain/` `datastore/`。schemas 侧**不给 tool 门面单开子包**——
`tools/` 代码层的四个门面保留（`CheckpointTool` 于步 5b 解散——存档归 harness 自己的状态模型），harness 经门面调模块的架构不变。

1. **信封 = 我们自己的模块间契约**，命名 `From[模块A]To[模块B][函数名][Req/Resp]`，
   **两半都放 A 处（发起方）**。强制适用范围是 **Harness ↔ 各门面**这一跳。
   **外壳（api / experiment）→ Harness 这条边不包装**：外壳不是我们的模块，
   入参与返回值都走裸字段——`run(run_id, goals)` 返回
   `(outcomes, total, succeeded, success_rate)`，`resume_run(run_id, episode_id, step)`
   同款；推给前端的 JSON 由 API 自己拼，形状归 API。（`submit_edit` /
   `latest_frame` 还带着信封，待统一。）
   注意别把这条推到记账层：**信封该内嵌模型就内嵌模型**——RUN_END 里的
   `RunResp` 由 `_close()` 内部组装，跟 `run()` 返回什么无关（第 5 条）。
   第一跳（调用方 → 模块门面）永远是信封，**门面上的每个方法都算**——
   `game_tool` 与 `memory_tool` 已于 0910 补齐（此前只有 `query_knowledge` 一条）。
   有入参就有 Req，返回结构化载荷就有 Resp；返回 None 的没有 Resp
   （`FromHarnessToGameToolResetReq` 是先例——`reset()` 返回 `None`）。
2. **模块对外的接口模型用裸名**，不带 From/To（providers 的 `LlmCompleteReq`、
   brain 的 `ChooseOnceReq`、world 的 `PerceiveOnceResp`、harness 的 `RunResp`）——因为发起方可能换人
   （今天 harness，明天第三方），From/To 前缀是赌一个注定被换掉的名字。
   **第二跳（门面 → 具体模块）走裸参数、返回模块自己的类型**，不造信封也不新建模型。
3. **豁免登记**（只有这两条，其余一律违规）：
   - `RunDataCenter` 直读——共享观察面，不是 RPC 语义。
   - **零参标量属性读取**：`TracePort.cursor`。没有载荷可装，套信封
     只剩一个空壳。
4. **domain 实体按产出方归属**；**跨包引用只允许向下**，登记如下：
   - 聚合方 → 被聚合方：`frontend → harness/brain`、`harness → 各家`、`memory → world`、
     `brain → world/memory`（`ChooseOnceReq` 天然要吃观测与记忆）。
   - `trace` 是**最底层共用层**，任何包可引用（`TraceEvent` 进 plan 上下文），
     它自己零跨包引用。`providers`（代码层实现包）0913 已解散——
     实现按"谁消费"回了 `brain/providers.py` 与 `memory/fastembed_*.py`。
     `schemas/providers/` 也随之一并解散（0913 深夜十一）：四封信是 brain 的
     内部协议、随 provider 进了 `brain/schemas/`，world 用自己的同名副本。
     账（`ModelCall`）的归属见下一行。
   - **代码层 `brain` 的引用面（0913 深夜九审计）**：**实现依赖只有 `tools/`**
     （`brain_tool.py` 4 处 + `vision_factory.py` 1 处）。`build.py` 对 brain
     **零 import**（两个工厂收在 tool 层）。其余包对 brain 的引用**一律是数据形状**
     （`Action`/`ActionSegment`/`Goal`/`Task`/`RunPlan`/`Reflection`/
     `EpisodeSummary`/`StepVerifyVerdict`/五个结果袋），共 54 处，分布：
     `harness/**` 21、`schemas/harness/communication/**` 17、
     `schemas/frontend/**` 1、`tools/prompts` + `tools/trace/render` 6、
     `tools/brain_tool` 4、`api.py` 1。**形状引用不是实现依赖**，不违反本铁律
     （跨层信封必须能内嵌这些形状，见第 1 条）。
   - **`ModelCall` 有三份归属、按"跨过哪道边界"分**：跨层信封那份住
     `schemas/harness/communication/ModelCall.py`（**带 `with_attempt`**，只有循环控制者盖章）；
     brain 方言那份住 `brain/interface/domain/model_call.py`（**不带**）；
     world 侧用裸 `dict[str, str]`（感知链路自记账、不跨层）。
     三份字段同构是巧合不是契约——**搬运点唯一**（`tools/brain_tool.py::_adopt()`）。
   - 叶子包之间零引用、**永不反向**：被调方不许 import 发起方的包。
5. **反向依赖的正解是改归属，不是摊字段。** 0910 的现场教训：
   `FromHarnessToTraceToolAppendReq` 内嵌 run 结算，而结算当时叫
   `FromFrontendToRunHarnessRunResp`、归在 frontend 包——记账层要内嵌它就得反向
   import 前端包（实测还成了 `schemas.frontend ↔ schemas.harness` 的循环 import）。
   正解是认出**这个模型本来就不属于那条边**：五个字段全是 `RunHarness._close()`
   自己数出来的，跟谁发起这次 run 无关，所以按第 2 条改成裸名 `RunResp`
   归 harness（入参那半直接摊成裸字段，见第 1 条），trace 内嵌它就是同包引用。
   **不要为了断依赖把结算摊成 `run_total`/`run_succeeded`/`run_success_rate` 这类裸字段**
   ——信封该内嵌模型就内嵌模型，摊平只是把归属错误藏进字段列表里。
