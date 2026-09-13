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

2. **大脑只能通过接口层与外界交互。** `brain/` 不许 import `harness/` 的任何具体实现，
   只许 import 各模块自己的 `interface/`（Protocol 定义，原来集中在顶层 `interfaces/`，
   现在物理挨着各自的实现——`world/interface/`、`brain/interface/` 等，见 CHANGELOG）。
   **`brain`/`world`/`memory`/`trace` 这几个领域模块之间、以及它们与 `schemas.*`
   之间，原则是完全没有相互依赖**——模块间只靠**裸函数**和 **tool 层**交互，
   不造信封；tool 层是唯一被允许同时认识多个领域模块、做信封拆装的地方
   （`world` 已经按这条原则完成裸字段化，其余模块正在推进，见
   `docs/PLAN_bare_boundary_refactor.md` 与 CHANGELOG 对应条目）。依赖方向永远是
   `brain → 各模块 interface/ ← harness`，**绝不反向，绝不横向**。
   *为什么*：这条一旦破，mock 换真实实现就要改大脑代码，原型的意义就没了；
   模块间零依赖是这一版重构消灭循环导入的根本手段——信封天然容易牵扯到别的
   模块的类型，形成隐蔽的双向依赖。
   *0913 更新*：原来"`providers` 例外，当作底层公共库"那句话已失效——代码层的
   `pokemon_agent/providers/` 整个解散，实现按"谁消费"回了 `brain/providers.py`
   与 `memory/fastembed_*.py`，**不再有横向的公共实现包**。
   *0913 深夜九补充*：**"谁依赖 brain"的唯一答案是 tool 层**。全仓库对 brain 的
   实现依赖只剩 `tools/brain_tool.py`（4 处）与 `tools/vision_factory.py`（1 处）；
   装配点 `build.py` 对 brain **零 import**——它要的两种东西都经 tool 层工厂拿
   （`BrainTool.build(text=…)`、`build_vision_provider(model=…)`），只递型号名。
   其余包对 brain 的引用一律是**数据形状**（`Action`/`Goal`/`Task`/`RunPlan` 等），
   不是实现依赖。

3. **mock 与真实实现必须实现同一个 Protocol。** 不许出现"mock 多一个方法"或"mock 签名不一样"。
   *为什么*：mock 的唯一价值是能被无痛替换。

4. **跨层传递的数据一律是 Pydantic 模型，不用裸 dict。**
   *为什么*：接口边界靠类型说话；后面接约束解码时 schema 直接复用。

5. **每一步都必须产出 trace 事件。** 没有 trace 的执行路径视为未完成。
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

- 每个模块的对外能力**先在它自己的 `interface/`（或没有专属数据形状的模块走扁平
  `ports.py`，见 `memory/`/`tools/`）里写成 `Protocol`（或 ABC）**，带完整类型注解和
  docstring，再去写实现。接口文件本身就应该是可读的设计文档：**光读各模块的
  `interface/`/`ports.py` 就能看懂整个系统怎么运转。**（历史上这些接口曾集中放在
  顶层 `interfaces/`，2026-09-11 逐个模块搬完后该目录已删除，见 CHANGELOG。）
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
├── schemas/          Pydantic 数据模型（跨层契约 + 本项目自己的记录形状）。
│                     `memory/`：记忆一族按**检索单元**命名——step_memory（一条=
│                     一步，`StepMemory`）/ episode_memory（一条=一整局，
│                     `EpisodeMemory`）/ object_fact（一条=一格，`ObjectFactEvent`）/
│                     knowledge（不挂坐标的先验）/ episode_summary_io（蒸馏那次
│                     调用的请求+响应，不是记忆）——这三类记录形状物理归这里而不是
│                     `memory/` 自己的包：`MemoryStorePort` 完全不透明（只收发裸
│                     字段/dict），从不需要知道它们具体长什么样，只有 tool 层/
│                     组装方（`brain.brain.py::reflect()`、
│                     `harness/object_interactions.py`、`tools/memory_tool.py`）
│                     才认识；`StepMemory.Observation`/`ObjectFactEventBase.Place`
│                     是各自的内部类，跟 `pokemon_agent.world` 的 `Observation`/
│                     `PlaceInWorld` 字段一致但类不互相引用，组装方用
│                     `.model_dump(mode="json")` → `.model_validate()` 转换。
│                     `world`/`trace` 不再有子包（`Observation`/`ActionSpace`/
│                     `TerrainMap`/`TraceEvent` 等已物理归回各自的模块，见下）
├── brain/            纯决策层。无状态。**`pokemon_agent.*` 外部依赖为零**——
│                     只剩标准库 + `pydantic` + `PIL`，**可作为第三方模块整体拷走**
│                     （0913 深夜十一审计）。异常自成一根 `BrainError`、四封补全信封
│                     （`LlmComplete*`/`VisionDescribe*`）已随 provider 搬进
│                     `brain/schemas/`——都是"拷走不欠外面"的必需品。
│                     `interface/`
│                     是这个子系统自己的港口 + 数据 schema 出口：`brain_port.py`
│                     （`BrainPort`）+ 六个数据形状（`Action`/
│                     `EpisodeSummary`/`Goal`/`RunPlan`/
│                     `StepVerifyVerdict`/`Task`，原来在
│                     `schemas/brain/domain/`）+ **`llm_config.py` 的
│                     `BrainLlmConfig`**（选型纯数据，0913 深夜九从
│                     `build_llm_providers.py` 搬来——它零重依赖，住在工厂模块里
│                     会让"只想声明型号"的调用方连带进口厂商实现面（含 PIL），
│                     实测从 25 个 brain 模块降到 14 个）。`brain/__init__.py` 对六个
│                     数据形状 + `BrainLlmConfig` 是立即加载，对 `Brain`（`brain.py`）/
│                     `BrainPort`/`build_llm_providers`（厂商接线工厂，拖着
│                     `providers.py` 整个实现面）都是**懒加载**——原因跟
│                     `world/__init__.py` 对 `WorldPort`
│                     的处理一样：`brain_port.py`/`brain.py` 都要
│                     `import pokemon_agent.schemas.brain`，而
│                     `schemas/brain/communication/*.py` 里的协议字段又要从
│                     这里拿回数据形状，两条依赖在初始化顺序上会正面相撞，
│                     取舍见 `CHANGELOG.md` 对应条目
├── harness/          控制循环本体（LangGraph 状态图），全项目唯一写 trace 的地方。
│                     **两张图、节点一人一个文件**：run 级 `run/`（`run_graph.py` +
│                     6 格在 `nodes/` 下：`begin`/`plan`/`dispatch`/`episode`/`reflect`/
│                     `review`——**包根只放骨架**，节点一律下沉一层）、
│                     episode 级 `episode/`（`episode_graph.py` + 21 格按
│                     七域 `open gate retrieve decide press store close` 分目录）。
│                     **规则：节点文件名 = 对应 `<level>_graph.py` 里 `add_node` 的
│                     字面量**（所以有 `retrieve/retrieve_step_episode_memory.py` 这种
│                     "看着冗余"的全名——basename 要能**单独**说清"我是哪张图的哪一格"）；
│                     结构性文件带层级前缀（`run_graph.py`/`run_entry.py`/`run_state.py`、
│                     `episode_graph.py`/`episode_entry.py`/`episode_state.py`）。
│                     `harness/` 根下只许**四个** `.py`（`__init__.py`/`deps.py`/
│                     `auto_reviewer.py`/`run_data_center.py`——**步 5a 起这是终态**，
│                     原先第五个 `trace_write.py` 已下沉 `tools/trace/model_calls.py`）
│                     + `run/`/`episode/`/`interface/` 三个目录。
│                     **入口是函数、不是类**：`run/run_entry.py` 的 `new_run`/`resume_run`
│                     （+`close`）、`episode/episode_entry.py` 的 `run_new`/`run_resume`；
│                     `RunHarness` 只剩 128 行薄类（`__init__(deps)` + 两个入口转调 +
│                     三个 `data_center` 委托 + `_compile`），唯一的构造参数是 `deps.py` 的
│                     `HarnessDeps`（缺省 `data_center` 在 `__init__` 里落实并**写回 deps**，
│                     保证节点与外部调用面拿到同一个对象）。常量各自跟着宿主节点住
│                     （`MAX_GOAL_RETRIES` 在 `run/nodes/reflect.py`；`MAX_PLAN_PUSH`/
│                     `PLAN_MAX_ATTEMPTS`/`RUN_TRACE_MASK` 在 `run/nodes/plan.py`；两个节点数常量
│                     在 `episode/episode_graph.py`；两层的 `recursion_limit` **各一个常量**——
│                     run 级是**闸门** `RUN_RECURSION_LIMIT`（`run/run_entry.py`，一个大数，
│                     不按公式算），episode 级是**贴身预算**，由 `episode_entry.episode_budget()`
│                     按剩余步数逐局算）。
│                     两张图的**交界键表**写在 `episode_graph.py` 的 `EpisodeInput`/
│                     `EpisodeOutput` 两个模型里（run 给一局什么、一局还 run 什么），
│                     `scripts/check_graph_phases.py` 机械核对"每个键都真的存在于两侧 state"。
│                     `interface/`：**只剩两个真端口**——`human_reviewer.py` 的
│                     `HumanReviewer` + 数据形状 `domain/human_decision.py` 的
│                     `HumanDecision`（原来在 `schemas/harness/domain/`）。判据是"实现方
│                     在不在系统之外"：`HumanReviewer` 的真实现是**人**；其余协作方都在
│                     系统内（靠 `HarnessDeps` 递），不该有 Port——原 `harness_port.py` 的
│                     `HarnessPort` 与 `episode_harness_port.py` 的 `EpisodeHarnessPort`
│                     两张 Port 因此已删（D5，见 `docs/spec/harness/PLAN_graph_composition.md`）。
│                     `harness/__init__.py` 对 `HumanDecision` 是立即加载，对
│                     其余全部（`HumanReviewer` + 状态模型 + 常量 + 全部实现类）都是
│                     **懒加载**——原因跟 `brain/__init__.py` 对 `Brain`/`BrainPort`
│                     的处理一样：这些文件都要 `import pokemon_agent.schemas.harness`，
│                     而 `schemas/harness/communication/FromHarnessToReviewerReviewResp.py`
│                     的字段又要从这里拿回 `HumanDecision`，两条依赖在初始化顺序上
│                     会正面相撞，取舍见 `CHANGELOG.md` 对应条目
├── world/            WorldPort 实现：PyBoy + 视觉模型的粘合层。`world/interface/`
│                     是这个子系统自己的港口 + 全部数据 schema 出口，跟"怎么读/
│                     怎么算"的实现文件物理分开，且**零依赖**（不 import
│                     `pokemon_agent.brain`、不 import `schemas.*`）：
│                     - `world/interface/`：协议——`world_port.py`（`WorldPort`，
│                       方法签名全部裸字段化：`reset`/`set_task` 收
│                       `task_id`/`goal`/`success_criteria`/`max_steps`/
│                       `initial_state_hint`，`step` 收
│                       `list[tuple[str, int]]`，`perceive_once` 返回
│                       `Perceived`，都不是别的模块的类型）+ `memory.py`
│                       （`Memory`，只要求"能按地址取字节"）；数据——
│                       `domain/facts.py`（`Facts`）、`domain/screen_state.py`
│                       （`ScreenState`）、`domain/terrain_map.py`（`TerrainMap`，
│                       `read_terrain` 的产出 schema）、`domain/observation.py`
│                       （`Observation`）、`domain/action_space.py`
│                       （`ActionSpace`）、`domain/place_in_world.py`
│                       （`PlaceInWorld`）、`domain/perceived.py`（`Perceived`，
│                       `perceive_once()` 的返回形状）、`domain/action_semantics.py`
│                       / `domain/screen_model.py`（跨模块常量）——后面这几个
│                       原来放在 `schemas/world/domain/`，按"模块间零依赖"这条
│                       原则物理搬回了这里
│                     - `pyboy_world.py` / `ram.py` / `frame_slot.py`：三份"怎么
│                       读/怎么算"的实现，各自 `from .interface import ...` 拿协议
│                       和数据形状来用，**不 import 任何 provider 实现**——它拿到的
│                       那个 `VisionProvider` 实例是**tool 层工厂**
│                       （`tools/vision_factory.build_vision_provider()`）造出来、
│                       由装配点 `build.py` 递进来的（0913 深夜九起：此前是
│                       `build.py` 直接从 `brain.providers` import，那是装配点
│                       伸进 brain 实现面的唯一一处），`world/` 自己一行
│                       都没提过 brain，不构成横向依赖
│                     `world/__init__.py` 对 `interface/`（含 `WorldPort`）是
│                     立即加载——零依赖之后不再需要懒加载；对
│                     `pyboy_world.py`/`ram.py`/`frame_slot.py` 这几个重实现文件
│                     仍是**懒加载**（`__getattr__` 按需导入），单纯是为了不让
│                     只要类型定义的调用方被迫连带拖着 PyBoy 一起 import，跟
│                     循环导入无关
├── tools/            `ports.py`：四个对外契约（`BrainToolPort`/
│                     `GameToolPort`/`MemoryToolPort`/`TraceToolPort`，原来在顶层
│                     `interfaces/tools/`）——扁平文件，
│                     没有自己专属的 domain schema，跟 `memory/ports.py` 同一个道理，
│                     零循环依赖风险，立即加载；`brain_tool.py`/
│                     `game_tools.py`/`memory_tool.py`/`trace/`（**步 5a 收成包**）：四个 Port 各自
│                     唯一的实现，harness 伸向 brain/环境/记忆/trace 的四只手。
│                     **两个接线工厂（0913 深夜九）**：`BrainTool.build(text=…)` 造
│                     大脑 + 四个 provider、`vision_factory.build_vision_provider
│                     (model=…)` 造 world 的感知 provider。**"谁依赖 brain"的唯一
│                     答案就是本层**——装配点 `build.py` 只递型号名，对 brain 零
│                     import。
│                     **步 5b 销账**：`CheckpointToolPort` + `checkpoint_tool.py` 已解散
│                     ——存档不是「能力」（没有第二种后端），它是 harness 自己状态模型的
│                     落盘能力，现住 `harness/episode/episode_state.py::EpisodeCheckpoint`
├── memory/           记忆子系统整块，**完全不认识** `StepMemory`/`EpisodeMemory`/
│                     `ObjectFactEvent` 这几个类——ports.py 对外契约
│                     （MemoryStorePort：只收发 `metadata: dict[str, str]` +
│                     `payload: dict` 两个裸字段，零依赖）+ store.py 统一记录存储
│                     （MemoryStore：一个 kind 一个文件夹 step_memory / object_memory /
│                     episode_memory / knowledge_memory，一条记录一个 uuid 文件 +
│                     每文件夹一份写穿倒排索引 index.json，可自愈重建）+ retrieval.py
│                     混合检索纯函数。三类被持久化的记录形状归 `schemas/memory/`
│                     （见该目录说明）——`StepMemory`/`ObjectFactEvent` 曾经短暂搬
│                     进来过，但 `MemoryStorePort` 从头到尾不需要知道它们的具体
│                     形状，只有 tool 层/组装方才需要，因此物理上搬回 `schemas/`
├── providers/        **0913 已解散（此目录不存在）**。协议更早各归其位
│                     （`LLMProvider`/`JudgeProvider` → `brain/interface/`、
│                     `VisionProvider` → `world/interface/`、
│                     `EmbeddingProvider`/`RerankerProvider` → `memory/`）；
│                     实现这次跟着协议走：`QwenProvider`/`ArkProvider`/
│                     `DeepSeekProvider` → `brain/providers.py`（`brain` 是主要
│                     消费者，四链路接线的知识本来就在 `brain/build_llm_providers.py`），
│                     `FastEmbedText`/`FastEmbedReranker` → `memory/fastembed_text.py`
│                     / `fastembed_reranker.py`（只被 memory 检索链路消费）。
│                     信封 `LlmComplete*`/`VisionDescribe*` 随 provider 进了
│                     `brain/schemas/`（大脑内部协议）；world 用自己的同名副本
│                     （`world/interface/domain/vision_describe.py`）
├── vision/           图像预处理（网格叠加、放大）
├── trace/            事件流：`interface/`（`TracePort` 协议 + `TraceKind` 账目
│                     词表，原来分别在顶层 `interfaces/trace/` 和
│                     `schemas/trace/domain/`，现在同住一包）+ `datastore/`
│                     （`TraceEvent`/`EventType`/`Source`/`TRACE_SCHEMA_VERSION`，
│                     原来在 `schemas/trace/datastore/`，物理搬回自己的包，
│                     `store.py`/`interface/trace_port.py` 改成相对导入）+
│                     `store.py`（`LocalTrace`：一条事件一个 json 落盘
│                     trace_data/<run_id>/events/）+ 事件 payload 组装
├── experiment/       实验任务定义（tasks.py）、experiment_states/（钉死存档）、
│                     real_check/（六维度真实链路核对）——仓库根级，不在包内
├── prompts/          所有 prompt 模板 + 组装辅助函数
└── build.py          唯一的装配点（全项目唯一 new 具体实现的地方）

tests/
CLAUDE.md          开发规范（本文件）
CHANGELOG.md       变更日志，每次改动追加
pyproject.toml
```

一个模块超过 300 行就拆。一个函数超过 50 行就拆。

## 五、编排：LangGraph

- 循环用 `StateGraph` 承载，**不手写 while 循环**。
- `LoopState` 是唯一的图状态载体，必须是 Pydantic 模型或 TypedDict，字段有明确类型。
- 节点函数是纯函数形态：`(state) -> state 增量`，副作用只允许发生在工具调用节点。
- **LangGraph 只管循环调度与状态传递。** 记忆层、状态表、值回填一律自己实现，
  不用 LangChain 的 Memory / Agent / Tool 封装。
  *为什么*：这些是本项目的原创部分，套框架抽象会讲不清楚也调不动。

## 六、LLM 与输出格式

- 本阶段已有真实 provider：`brain/providers.py` 的 `QwenProvider`（DashScope、
  语言+视觉两用）/ `ArkProvider`（火山方舟、豆包）/ `DeepSeekProvider`，
  `memory/fastembed_text.py` 与 `memory/fastembed_reranker.py`（本地向量化与重排）；
  通过 `LLMProvider`/`JudgeProvider`（`brain/interface/`）、`VisionProvider`
  （`world/interface/`）、`EmbeddingProvider`/`RerankerProvider`（`memory/`）接入。
  （0913 前它们都住顶层 `providers/`，那个包已解散。）
  代码里**不许出现任何直连模型 SDK 的调用**——直连只发生在这几个实现文件里。
- 动作选择输出用 **Pydantic schema**（`Thought` / `Action` / `Args`）解析。
- **解析失败要重试并计数**，重试次数与失败计数进 trace。不许静默吞掉解析错误。
- 约束解码（constrained decoding）留到接真实模型时再上，现在不做。

## 七、代码风格

- Python 3.11（不是 3.10——`enum.StrEnum` 要 3.11 才有，`schemas/trace/domain/trace_kind.py` 等用到）。所有公开函数、方法、Pydantic 字段**必须有类型注解**。
- `ruff` 管 lint + format，行宽 100。提交前跑 `ruff check . && ruff format .`。
- 命名用完整英文单词，不用缩写（`action_space` 不是 `act_sp`）。
- 注释只写**为什么**，不写做了什么。代码讲不清的取舍才写注释。
- 不写 README 除非明确要求；说明写在 CLAUDE.md 或 docstring。

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
| `type` | 7 类（`pokemon_agent/schemas/datastore/__init__.py::EventType`，见 `docs/spec/DATAFLOW.md` 2.2）：`model_call` / `error` / `llm_outcome` / `view` / `act` / `memory_io` / `lifecycle`。**0903 收敛原则**：type 与生产者（source）正交、数量极小；原 20 类里"哪个节点/哪类产物"的语义全部降级为 `payload.kind`（如 llm_outcome=intent/verdict/audit、memory_io=read_*/write_*、lifecycle=run/episode 边界 + step） |
| `valid` | 废弃分支标记，默认 `true`。checkpoint 的 `void_after` 把游标之后的事件**原地**打 `valid=false`（不删不挪）；读端只收 `valid=true`。resume 写新 event_id、从不重用旧号 |
| `payload` | 该类型的结构化内容 |
| `ts` | 时间戳 |

- trace 是**追加写的事件序列**，不是可变状态快照。checkpoint 存事件序列而非最终状态。
- 落盘形状（0910 起）：一条事件一个 json，`trace_data/<run_id>/events/<run_id>-<event_id>.json`；
  截图与事件共用 event_id，落 `trace_data/<run_id>/screenshot/<event_id>.png`（resume 不作废截图）。
  `LocalTrace._next_id` 从盘上 max(event_id)+1 现算，接口按"能落盘、能重放"设计。

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
