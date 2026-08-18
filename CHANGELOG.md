# 变更日志

> 最新在最上。每条固定四段：改了什么 / 为什么这么改 / 取舍 / 影响面。
> 这是给人读的决策记录，不是 git log 的复制品。

## 2026-08-18 —— 论据进记忆：Action 加 rationale，thought 只进 trace

**改了什么**
`Action` 新增 `rationale: list[str]`（1-`MAX_RATIONALE` 条，必填），`thought` 从
`default=""` 改为必填非空。`_parse` 拆出 `_parse_thought` / `_parse_rationale`，
两类缺失各自单列 reason。`remember()` 改用论据合成记忆内容，prompt 模板相应改写。
另修两处旧问题：ACT 事件的 step 改用执行前的值；删掉 `observe` 节点里不可达的
done 分支。测试 9 → 13，ruff 由 1 个 I001 转全绿。

**为什么这么改**

先是发现 `thought` 根本没跨步：它唯一的消费方是 `trace.append`，`remember()` 拼
记忆时不含它。推理产出后立刻被截断，再也不进入任何后续决策。这与本项目自称 ReAct
是矛盾的——ReAct 的分界线不是"先想后做"（那太平凡），而是**第 t 步的 thought 能不能
被第 t+k 步看见**。原论文的 HotpotQA 轨迹里 thought 与 action 本就是同一步给出的，
所以"thought 是不是独立动作"不构成判据，**能不能跨步**才是。

但这是实现没落地，不是设计选择——设计一直打算让推理跨步，走检索而不是拼接。
于是**保留 ReActBrain 这个名字**，把代码补上。

顺带纠正一个此前想反了的问题：**检索式 scratchpad 不是对机制三的妥协，是让
scratchpad 与 episodic control 共存的解法。** 原版 ReAct 的上下文随步数单调增长，
同一个状态在第 3 步和第 300 步面对的输入必然不同，这才是系统性破坏近似 Markov 性
的那个；而按状态相关性检索，相似状态取回相似记忆，被注入的内容近似是**状态的函数**，
反而维持了它。附带收益是上下文不随步数爆炸，长程任务上才跑得下去。

那么跨步的该是什么？不是完整推理，也不是结论：

- **结论**（"所以该捡药水"）可以从 `name` 反推，存进去等于把同一件事存两遍。
- **完整推理**里大部分是本次决策的中间步骤，对未来无用，还挤占检索名额与 token。
- **论据**（"地上有药水而我手上没有"）才是 `name` 里没有的信息，而且它是**适用条件**
  ——未来取回这条经验时可以检查它现在还成不成立。结论做不到这件事。

所以分工定为：`thought` 服务本次决策的质量（长度即算力，不设上限，只进 trace），
`rationale` 服务未来的迁移（短、可证伪、进 memory）。

还有一个白拿的性质：记忆条目由「模型出假设 + 世界出判决」拼成，天然**自带标签**
（"我以为 P，结果 R"）。一条错误论据被取回时反例就贴在同一行，不会被当成知识使用。
这让"记忆被无用内容污染"的风险比预想的低——脏东西是带标签的脏东西。

**取舍**

- **论据不区分时效性，一律按有时效处理。** 曾考虑给持久知识（"馆主是火属性"）单独
  开池 + 去重，因为它会被反复产出。放弃了：rationale 是**条目内部的字段**，重复只
  造成 token 膨胀，**不占检索名额**，危害远小于估计。代价是持久知识只能绑在发现它
  的那一步上，跨状态检索不到——那属于 skill library（机制二）的范围。
- **超上限打回重试，不截断。** 模型认为 N 条都承重，悄悄丢一条是替它做了个没有记录
  的决定。代价是这类重试要花 token；实测占比高再改成截断。
- **单条写成裸字符串则容忍**，不消耗重试。判据同 ```json 包裹：常见格式偏差、语义
  无歧义、为它跑一轮重试不划算。
- **`MAX_RATIONALE` 抽成常量**。它有两个执行点（`Action` 的字段约束 = 数据契约，
  `_parse` = 外部输入校验），写死两遍迟早漂成"解析器放行、构造时炸"。
- **缺失用 reason 字符串区分，不新增异常类型**。replay 按 reason 聚合就能把"格式坏"
  和"不肯给论据"拆开，够用了，不值得为它多一个异常类。
- **ACT 的 step 取自 `get_action_space()` 时缓存的值**，而不是执行后 `-1`，也不是
  重新 `observe()`。后者在真实模拟器上是「截图 + VLM」，为记一条日志再感知一次太贵；
  前者依赖 world 的后置条件做减法，且 observation 为 None 时无解。缓存复用的是
  `get_action_space()` 里已经取到的那次观测，免费且在两条路径下都正确。
- **`observe` 的 done 分支直接删，换成一条 assert**。它永远不执行（两条入边都保证
  未结束），而且返回 `action_space=None` 会让下一节点的 assert 崩在更远的地方——
  按第三节第 4 条的判据，不改变行为的"防御"不该存在。

**影响面**
`Action` 的构造点只有 `_parse` 一处，无其他调用方受影响。`MemoryEntry` 签名未动，
key 仍是 step 占位。`FakeLLM.scripted()` 自动把 thought 复制为 rationale，因此所有
只关心动作序列的既有测试一行未改。ACT 的 step 修正会改变 trace 的形状——阶段 2 的
按 step 聚合建立在这次修正之上，**先改再堆**。

## 2026-08-13 —— 更正：harness 与 trace 也是 mock，移进 mocks/

**改了什么**
`harness/harness.py` → `mocks/mock_harness.py`（类名 `Harness` → `MockHarness`），
`harness/trace.py` → `mocks/mock_trace.py`（`InMemoryTrace` → `MockTrace`）。
`harness/` 包不再使用（挂载盘不允许删除，其 `__init__.py` 已移到 `_to_delete/`，
请在本地删掉这个空目录和 `_to_delete/`）。两个模块的 docstring 重写，明确列出它们缺什么。

**为什么这么改**
上一条我用"是否完整实现契约"当判据，把 InMemoryTrace 归成了真实实现。判据用错了。
**这一阶段的范围是"只做大脑，其余全部 mock"**，harness 和 trace 都在"其余"里：

- MockHarness 的 masking 是写死的 if 分支（不是从状态表查）、记忆检索是字符集重叠
  （没有 state abstraction、没有值回填），六件套只有 trace 一件，
  缺权限确认、沙箱、成本控制、checkpoint、replay，动作空间不会增长。
- MockTrace 只是个内存列表，不落盘、不推流、不做 checkpoint 事件源、不按失败类型聚合。

它们后面是要被**重写**的，不是"换个存储介质"。放在 `harness/` 会让人以为那是成品，
导致后面接着往上堆而不是推倒重来。

**取舍**
保留"替身也严格遵守契约"这一点（MockTrace 的 event_id 仍然真的单调、
MockHarness 的 precondition 断言一个没少）。替身可以简陋，不能违约——
否则换成真实实现时上层会崩，mock 的意义就没了。这条写进了两个文件的 docstring。

`mocks/` 现在有四个文件（fake_llm / mock_world / mock_harness / mock_trace），
对照之下 `brain/` 只有一个 —— 这个比例恰好说明了当前阶段的范围。

**影响面**
纯搬迁与改名，9 个测试仍全绿，ruff 无告警。

## 2026-08-13 —— 最小闭环跑通（mock + harness + 图装配 + 测试）

**改了什么**
新增 `mocks/fake_llm.py`、`mocks/mock_world.py`、`harness/trace.py`（InMemoryTrace）、
`harness/harness.py`、`graph/build.py`，以及 `tests/test_react.py`（5 个单元测试）和
`tests/test_episode.py`（4 个集成测试）。9 个测试全绿，ruff 无告警。

**为什么这么改**
到这一步"最小闭环"才成立：一个任务从头跑到尾、全程有 trace、失败路径有计数。
几个位置的决定：

- **InMemoryTrace 放 `harness/` 而不是 `mocks/`**。判据：实现的是完整契约就进 harness，
  只为让流程跑通的替身才进 mocks。它的 event_id 真的单调、replay 真的能回放，
  和将来的 FileTrace 只差存储介质，而且测试会一直用它（测试不该往磁盘写东西）。
- **masking 在 harness，成败判定在 world**。掩码是策略（什么时候允许买东西是设计决定），
  判定是能力（只有世界知道状态是否满足判据）。这条边界写进了 Harness 的模块 docstring。
- **`execute()` 前要先 `get_action_space()`**，harness 记住最近一次给出的空间做 precondition，
  执行后立即置空——世界推进了，上一次的动作空间就失效了。
- **AgentState 只存流转数据，不存业务状态**。业务状态在 harness 里。
  因为图状态会被 LangGraph 复制、合并、快照，把记忆或世界塞进去会产生意料之外的副本。
- **FakeLLM 支持返回坏 JSON 和 loop 模式**。解析失败与重试是大脑最重要的一条分支，
  没有能制造失败的 mock 就测不到它。

**取舍**
- `memory_query` 用字符集重叠打分，粗糙。故意不上 embedding：
  换向量检索是机制一的事，现在上会掩盖"检索策略属于实现方"这个分层是否真的成立。
- `MockWorld` 的 DEMO_TASK 只有 12 步上限，**不满足 Task docstring 写的下界**
  （必须长到上下文装不下）。代码注释里标了这一点：它只是让闭环跑起来的脚手架，
  真实任务集要另行设计。
- `build_demo()` 返回 harness 和 trace 三元组，比只返回图啰嗦。
  但测试要读 trace 做断言，不返回就得从图里掏，那才是真的破坏封装。

**影响面**
全项目可运行。`pytest` 通过即表示：换真实模拟器只需换 `MockWorld`、
换真实模型只需换 `FakeLLM`，brain 和 harness 一行不动。

## 2026-08-13 —— episode 的边界从"通关"改成"一个任务"

**改了什么**
`schemas/core.py` 新增 `Task`（task_id / goal / success_criteria / max_steps）和
`EpisodeOutcome`；`Observation` 加 `goal` 与 `success` 两个字段。
`WorldPort.reset()` 改签名为 `reset(task)`，`step()` 的契约补上成败判定与终止条件。
`ToolPort.perceive()` 后置条件补 goal。`ReActBrain` 的 prompt 加"当前任务目标"一节，
`choose()` 入口增加两条 precondition（episode 未结束、goal 非空）。

**为什么这么改**
原来一个 episode = 一次通关，粒度太大，三处都出问题：

1. **机制三拿不到信号**。通关是几千步只产出一个 0/1 结果，
   MC 回填的折扣一路乘下去，回填到前期步骤上几乎是噪声。任务级几十到几百步才有梯度。
2. **评测只能报二值结果**。任务级能报成功率、失败模式分布、有记忆 vs 无记忆的对比——
   这才是"提升了多少"要的形态。
3. **迭代周期以小时计**，每改一行都要跑一次通关才有反馈。

**取舍**
- **"长程"这个卖点会被稀释**：任务缩得太小，一个上下文窗口就装下了，记忆架构失去存在理由。
  所以在 `Task` 的 docstring 里写死了下界：必须长到单靠上下文装不下、
  必须跨任务复用经验才做得好。这条判据要在设计任务集时守住。
- 采用两层结构：**episode = 一个任务**（回填与评测单位），**通关 = 一串 episode**（future work，不实现）。
  额外收益是 episodic 记忆有了清晰的作用域：**一条轨迹 = 一个 episode = 一次任务尝试**，
  MC 回填的边界与检索的相关性范围都由此确定。
  （注意别把"跨任务复用的经验"叫 semantic —— semantic 是外部领域知识，
  比如"水属性克制火属性"，来自攻略/图鉴而非自己跑出来的轨迹。
  跨任务复用的成功经验属于 episodic 的聚合，或晋升后进 skill library。）
- 成败判定放在 `WorldPort` 而不是 harness：只有世界知道游戏状态是否满足判据。
  代价是 mock world 要实现判定逻辑。

**影响面**
接口签名变更（`reset`），但尚无实现，无返工。`Task` 与 `EpisodeOutcome` 是新增，
`Observation` 的两个新字段有默认值，不破坏已有构造。

## 2026-08-13 —— 实现 ReActBrain（大脑，唯一的实现代码）

**改了什么**
新增 `brain/react.py`：`ReActBrain.choose()`（一轮 Thought → Action，含重试）、
`remember()`（写记忆）、三个私有方法（`_recall` / `_build_prompt` / `_parse`）。

**为什么这么改**
几个位置的决定：

- **重试放在大脑里，不放在 LLMProvider 里**。因为"什么算失败"是大脑的判断——
  解析不出来算失败、选了不存在的动作也算失败，这两件事 provider 都不知道。
- **ParseFailure 与 IllegalAction 分开抛**。它们在 replay 里是不同的失败模式：
  前者说明格式没学会（改 prompt 或上约束解码），后者说明模型在幻觉动作（改动作说明或收紧掩码）。
  合并成一类就丢掉了这个诊断信息。
- **每次重试重新调用 LLM 而不是复用上次输出**。模型的随机性本身就是重试有意义的原因。
- **`_build_prompt` 每次从参数完整组装，不留历史**。这是"大脑无状态"在代码层面的落点：
  想违反铁律 1 就必须在这里加一个实例变量，很显眼。
- **容忍 ```json 包裹**直接在解析里处理，不消耗一次重试——这是模型最常见的格式偏差，
  为它跑一整轮重试不划算。

**取舍**
- 大脑自己写 trace（COST / THINK / ERROR / MEMORY_READ / MEMORY_WRITE 五类），
  而不是由外层统一收集。代价是大脑多依赖一个 TracePort；
  收益是 token 成本只在 LLM 调用点拿得到，绕出去就要让成本模块认识 LLM 层，破坏分层。
- `choose()` 需要 `episode_id` 参数，签名比"只传 obs 和 space"啰嗦。
  但大脑无状态就意味着它不能自己记住当前是哪个 episode，只能由调用方每次传入。
- prompt 用字符串模板而非模板引擎：原型期够用，且模板内容一眼可见。

**契约落点（对应第三节第 4 条）**
构造函数 assert `max_retries >= 1`、`memory_limit >= 1`（pre）；
`choose()` 入口 assert 动作空间非空（pre）、出口 assert 返回动作在空间内（post）；
`_recall` assert 返回条数不超过 limit（对 ToolPort 后置条件的交叉验证）；
`remember()` assert result 非空（pre）。

**影响面**
新增。依赖四个 Protocol，不依赖任何实现。此时还跑不起来——缺 FakeLLM、MockWorld、
Harness、InMemoryTrace 和图装配。

## 2026-08-13 —— 接口层设计（只有 Protocol 和数据模型，无实现）

**改了什么**
新增 `schemas/core.py`（7 个 Pydantic 模型）、`errors.py`（3 类预期内失败）、
`interfaces/` 四个 Protocol：`LLMProvider` / `ToolPort` / `TracePort` / `WorldPort`。
所有方法只有 docstring 契约，方法体是 `...`。

**为什么这么改**
按"接口先行"，先让 `interfaces/` 成为可读的设计文档。几个关键决定：

- **ToolPort 与 WorldPort 分开**。ToolPort 是"大脑能做什么"（五个 MCP 工具），
  WorldPort 是"世界能做什么"（reset/observe/all_actions/step）。harness 用后者实现前者。
  换真实模拟器时只动 WorldPort 的实现，ToolPort 和大脑一行不改。
  masking 放在 harness 而不是 world，因为掩码是策略不是能力。
- **LLMProvider 做得极薄**，只有 complete()。重试是调用方策略、约束解码将来加新方法、
  对话历史由无状态的大脑每次组装——三样都不进这个接口。
- **TracePort 只有 append 和 replay，没有删改**。append 返回 event_id 而不是事件，
  是为了落盘实现能在这里分配序号；replay 带 after_event_id，直接对应 SSE 的 Last-Event-ID。
- **IllegalAction 异常与 execute() 入口 assert 并存**，针对两个责任方：
  前者是大脑内部发现模型幻觉（外部输入不合法 → 重试），后者防大脑没检查就把动作递出去（调用方 bug）。

**取舍**
- `Action` 里带 `thought` 字段：数据模型里混了调试信息，不够纯粹。
  但 replay 时只知道选了什么、不知道为什么选，价值折半，值这个代价。
- `ToolResult.observation` 可为 None，调用方需另行 perceive()：多一次调用，
  换来"推进世界"和"读取世界"两件事不被绑死。
- `MemoryEntry.key` 本阶段用 step 占位。机制一接进来时这里换成 state abstraction 的语义 key，
  **接口签名不变**——这是检验抽象对不对的试金石。

**影响面**
新增，无既有代码。下一步的实现与 mock 全部按这四个 Protocol 写。

## 2026-08-13 —— 明确 assert 的定位：契约（pre + post + invariant）

**改了什么**
`CLAUDE.md` 第三节第 4 条重写为契约式设计的完整三件套，给了 pre/post 的代码示例，
并补了"不做流程控制/兜底/外部输入校验"的判据。

**为什么这么改**
第一版把 assert 摊成"前置 + 后置 + 各种不变量"，边界糊；第二版矫枉过正只留 precondition，
把 postcondition 推给测试，这是错的——测试只覆盖想到的用例，出口 assert 覆盖所有实际执行。
本项目最核心的主张"大脑不会幻觉出不存在的动作"，最好的运行时证据就是 `choose()` 出口的
一行 postcondition assert。

关于边界，判据收敛成一条可机械判断的：`python -O` 会删掉所有 assert，
删掉后程序行为会改变的东西就不该是 assert。这一条同时排除了兜底、副作用和外部输入校验，
不需要三条独立规则去记。

**取舍**
出口 assert 有运行时开销，且在热路径上会重复检查。原型期不管这个——
真到了性能敏感的地方，`-O` 本来就是关掉它们的正规手段。

**影响面**
规范层面。尚无代码，无返工。

## 2026-08-13 —— 立项：定开发规范与工程配置

**改了什么**
新建 `CLAUDE.md`（开发规范）、`pyproject.toml`（ruff 行宽 100 + pytest）、`.gitignore`、本文件。
尚未写任何业务代码。

**为什么这么改**
项目的架构约束（大脑无状态、依赖单向、trace 是四件事的共同底座）如果不先写死，
原型期会以"先这样以后再改"的名义被逐条破坏，而这几条一旦破了，
后面的 replay / checkpoint / SSE 观测台全部要重做。规范先行的成本远低于返工。

**取舍**
- 上 LangGraph 而不是手写 while 循环：少一次重写，代价是一开始要和框架抽象磨合。
  但只让它承担循环调度，记忆与状态表自己实现，磨合面被限制住了。
- 输出格式先用 Pydantic + 解析重试，不上约束解码：原型期没有真实模型，
  约束解码会把实现和具体模型能力绑死。
- 不引入 mypy / pre-commit：原型期摩擦大于收益，ruff 的 ANN 规则已经强制了类型注解。

**影响面**
全项目。后续所有代码都受 `CLAUDE.md` 约束。
