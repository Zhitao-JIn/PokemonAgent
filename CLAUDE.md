# Pokemon_Agent —— 开发规范
> **本文件是 `AGENTS.md` 的镜像副本**（Claude Code 读这一份）。
> **有冲突时以 `AGENTS.md` 为准**；要改规范请改 `AGENTS.md`，再把内容同步到这里
> （除本句外两份应逐字一致；本仓库历史上这份曾是分叉的旧副本，2026-09-15 已同步并加此声明）。

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
   依赖方向永远是：模块只认自己的 Port，门面层（`direct/` / `mcpclient/`）认识两边的形状并做转换。
   **协议的归属看"谁消费"不看"谁实现"，实现也跟着协议走**——`providers/` 这个包 0913
   已解散：`QwenProvider`/`ArkProvider`/`DeepSeekProvider` 进 `brain/providers.py`，
   `LocalEmbeddingProvider`/`LocalRerankerProvider` 进 `memory/`。
   **"谁依赖 brain"只有唯一答案：tool 层（0913 深夜九审计定案）。** 全仓库对
   `brain` 的**实现依赖**（`Brain`/`BrainPort`/`BrainLlmConfig`/`build_llm_providers`/
   厂商类）现在只剩门面层（`direct/` + `mcpclient/`）五处；装配点 `build.py` 对 brain **零 import**——
   它经 tool 层的接线工厂 `BrainTool.build(…)` 造大脑。装配只递配置节里的裸字段，
   `BrainLlmConfig` 由 `BrainTool.build()` 内部构造。
   （`harness`/`schemas`/`world` 对 brain 的引用一律是**数据形状**
   （`Action`/`Goal`/`Task`/`RunPlan`/`EpisodeSummary`/
   `StepVerifyVerdict`/七个结果袋），不是实现依赖，见第十二节第 4 条。）
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
- 接口保持简单：每个方法只做一件事、签名一眼能读懂；不按方法个数机械拆分。

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

本项目的典型契约：`GameTools.execute()` 入口断言每个段的按键名在动作空间内（pre）；
`Brain.choose()` 出口断言返回的动作段非空、且每个段名都在本步的按键表里（post）；
`TraceTool.append()` 入口断言 `req.meta` 带齐 `source`/`episode_id`/`step` 且**不带** `run_id`（pre），
出口断言落盘事件的 `kind` 只许是请求点的那本账、或一条连带产出的错误账（post）；
核对器对**盘上历史**事件断言 `set(meta) == set(node_io.META_KEYS)`（invariant）。

### 5. 测试是用法示范，不是覆盖率任务

测试的第一读者是**想知道这东西怎么用的人**（包括三个月后的你和面试官）。所以：

- **单元测试**：每个接口至少一个，展示"最简单的正确用法长什么样"。
- **集成测试**：至少一个端到端——`FakeLLM + MockWorld` 跑完整 episode，
  从装配到断言全部可见，**这个测试就是项目的使用说明书**。
- 测试要读起来像文档：Arrange / Act / Assert 三段用空行分开，
  测试函数名是一句话（`test_brain_never_picks_action_outside_space`）。
- **不追覆盖率、不测私有函数、不写 mock 套 mock 的测试。**
  测试难写说明依赖注入没做好，回去改设计而不是加 mock。

### 6. git commit 规范 —— 对应 CHANGELOG.md 条目，分步提交

- **一条 CHANGELOG.md 编号条目 = 一个（或一组）commit**。不要把多条改动揉进一个 commit，
  也不要把一条改动拆得比 CHANGELOG 条目还碎。
- **所有 commit 一律带 Conventional Commits 前缀**（`feat:` / `fix:` / `refactor:` / `docs(scope):` / `chore:` 等），
  可以带简短 body 说明范围。
- **有对应编号条目的 commit**：前缀之后**逐字复用**该条目的标题文字（去掉 `**`、反引号等 Markdown 修饰符），
  让 commit 与 CHANGELOG 条目能按编号对上；body 只写范围，理由不在 git log 里重复——已经写在 CHANGELOG.md 里。
  例：CHANGELOG 标题是 `## 2026-09-13（61）—— trace 脱钩落地：非 tool 层对 pokemon_agent.trace 的 import 清零`，
  对应 commit 标题就是 `refactor(trace): 2026-09-13（61）—— trace 脱钩落地：非 tool 层对 pokemon_agent.trace 的 import 清零`。
- **没有对应编号条目的 commit**（零散收尾、格式修正、文档同步等日常维护）：同样用前缀，标题自拟。
- **一次性追提多条积压的编号条目时，按编号从小到大依次提交**，保持 commit 顺序与 CHANGELOG 顺序一致。
- CHANGELOG.md 本身的 diff（追加新条目）只随**最后一个**相关 commit 一起提交，不要在中途逐段拆分它
  ——历史上尝试过按行区间手工拼接，撞过 CRLF/LF 混用导致整份文件误判为全量替换的坑。

## 四、目录结构

```
pokemon_agent/
├── schemas/          Pydantic 数据模型（跨层契约）。记忆一族按**检索单元**命名：
│                     act_memory（一条=一键，**源记录**）/
│                     task_memory（一条=一个 task，该 task 全部 act 记忆带正负标注的蒸馏）/
│                     episode_memory（一条=一整局，该局全部 task 记忆带正负标注的蒸馏
│                     ——派生物，可重建、可丢弃）/
│                     object_fact（一条=一格）/ knowledge（不挂坐标的先验）/
│                     episode_summary_io（蒸馏那次调用的请求+响应，不是记忆）
│                     其余：Observation / Action / ActionSpace / TraceEvent / Completion。
│                     `harness/communication/ModelCall.py` 是**跨层信封**那份账
│                     （brain 方言另有一份，两份**字段同构、按"谁产出谁消费"分家**，
│                     都不是"第几次尝试"的载体，见第十二节第 4 条）
├── brain/            纯决策层。**可整体拷走复用的第三方模块**——只依赖自己声明的
│                     两个 provider 契约与 errors，**不知道 harness / world / memory
│                     的存在**。对外只有 `interface/brain_port.py`（七方法裸字段契约）
│                     与 `interface/domain/`（brain 自己的方言：Action/Goal/Task/
│                     RunPlan/Decomposition/EpisodeSummary/VerifyVerdict + 各方法的结果袋
│                     + `model_call.py` 那份 **brain 方言**的账，归属见第十二节第 4 条）
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
│                     **只依赖 direct / mcpclient / schemas 三层，不依赖 trace 的实现**
│                     （trace 也是独立模块，只通过 Port 说话）
│                     checkpoint/：三级存档（run 开局 / 每局开派前 / 每个 task 开局）
│                     + 图内恢复到任意一级（Checkpointer / restore_run；血缘从 trace 推，
│                     见 docs/spec/checkpoint/）；reviewing.py：问人的唯一入口（每问记一笔）
├── world/            WorldPort 实现：PyBoy + 内存观测 + 世界语义常量
│                     （INTERACT_KEY / DIRECTION_KEYS——"这个世界怎么按键"的知识）
├── direct/           Harness 伸向 brain / trace 的手（原 `tools/` 的 brain/trace 半边，
│                     P7 拆分）：`brain_tool.py` / `trace/` / `interface/`
│                     （四张 Port 协议）。**跨模块的双向转换一律在这一层**
│                     ——tool 认识两边的形状，是唯一的桥
├── prompt/           prompt 模块：唯一渲染出口。`PromptGateway.render(task, params)`
│                     返回 `RenderedPrompt{text, task, version, hash}`；`registry.json`
│                     决定唯一生效版本。任务与片段按版本目录存放（`prompt.md` +
│                     `assemble.py`），只接收字段，不持有世界 / 记忆对象。
├── mcpclient/        Harness 伸向 memory / world 的手（原 `tools/` 的 memory/world 半边）：
│                     `memory_local.py`（进程内 MemoryTool）/ `memory_tool.py`（MCP 远程
│                     MemoryMcpTool）/ `game_tools.py`（进程内 GameTools）/ `world_tool.py`
│                     （MCP 远程 WorldMcpTool）/ `client.py`（同步外观异步内核）。
│                     **接线工厂**（参数一律来自 `AppConfig` 的对应节）：
│                     `BrainTool.build(links=…, …)` 造大脑 + provider、
│                     `ReviewerTool.build(review, flush=…)` 按 `review.mode`
│                     （off/human/ai/both）造复核席（住 `direct/reviewer_tool.py`）、
│                     `WorldMcpTool.build(world_server_url=…)` 连接 world server
│                     （只经 MCP，URL 必填）、
│                     `MemoryTool.build(memory_server_url=…, memory_root=…)` 只经 MCP（URL 必填）、
│                     `TraceTool.build(run_id=…, trace_root=…)` 造 `LocalTrace`。
│                     **"谁依赖 brain"的唯一答案就是 direct + mcpclient 两层**——
│                     装配点 `build.py` 只递型号名 / 路径 / server 地址这类裸字段
├── memory/           memory 子系统整块（契约 + 实现 + 算法，可整体拷走复用）：
│                     ports.py 是对外契约（MemoryStorePort）；store.py 是统一记录
│                     存储（LocalMemoryStore：一条记录一个 <uuid>.json/.md + 每文件夹
│                     倒排索引 index.json + 向量 sidecar vectors.jsonl）；
│                     retrieval.py 是混合检索纯函数（BM25 + embedding + RRF +
│                     reranker，只认字符串，不认记忆类型）；
│                     embedding_provider.py / reranker_provider.py 是本模块消费的
│                     两个协议。
│                     只做读写与索引，不做语义判定（见下方分层原则）
├── providers/        **0913 已解散**——实现按"谁消费"回了各自模块：
│                     `QwenProvider`/`ArkProvider`/`DeepSeekProvider` →
│                     `brain/providers.py`；`LocalEmbeddingProvider`/`LocalRerankerProvider`
│                     → `memory/fastembed_text.py` / `fastembed_reranker.py`。
│                     协议则更早各归其位：LLMProvider/JudgeProvider → brain.interface；
│                     Embedding/RerankerProviderPort → memory。
│                     **本目录不再存在。**
├── trace/            独立模块：TracePort 契约 + LocalTrace（落盘）+ 事件类型词表。
│                     它不是 harness 的内部件——harness 只经 TraceToolPort 说话
├── review_backend/   独立后端（WS 服务，顶层包）：收 harness 跳 A `/harness`、广播前端
│                     跳 B `/ui`、连 agent 跳 C。零 harness 依赖（不起 run 图）；
│                     `python -m pokemon_agent.review_backend [--port]`
├── agent_reviewer/   独立进程视觉 LLM 复核席（deepseek-flash V4.1 原生视觉，地址走
│                     `.env` 的 `AGENT_REVIEWER_URL`）：经跳 C WS 收后端 seed/turn/close、
│                     推 `proposal`；`python -m pokemon_agent.agent_reviewer`。不进 harness /
│                     后端进程，不依赖 brain
├── experiment/       实验任务定义（tasks.py）、experiment_states/（钉死存档）、
│                     real_check/（真实链路核对：维度 1 harness / 2 trace /
│                     3 checkpoint / 4 memory / 6 memory roundtrip；编号 5
│                     随旧 restore 维度一起删了）——仓库根级，不在包内
├── settings/         **全项目唯一的配置中心**（取代旧 `config.py` / `run_config.py` /
│                     `run_budget.py`）：全部 JSON。`default.json` 是随包保底值，启动时
│                     可叠任意多个覆盖文件（深合并：dict 递归、list/标量整体替换），
│                     `load_config(overlays)` → `ResolvedConfig`（冻结的严格 Pydantic
│                     `AppConfig` + 来源 + 合并后 JSON + sha256）。每次 run 把合并结果
│                     落成 `paths.config_snapshot` 下的快照文件。密钥（API key /
│                     LANGFUSE_*）只在 `.env`，绝不进 JSON。判据——"改这个数是为了做实验
│                     还是为了让代码正确"：前者进 settings，后者（帧数、内存地址、
│                     网关下界等模块私有物理量）留在各自模块；独立模块
│                     （brain/memory/trace/world）不许 import `pokemon_agent.settings`
└── build.py          唯一的装配点：`build_real(config=None)` 只收配置文件路径（一个或
                      多个覆盖层），其余全部读 `AppConfig`；全项目唯一 new 具体实现的地方

tests/
AGENTS.md          开发规范（本文件）
CHANGELOG.md       变更日志，每次改动追加
pyproject.toml
```

memory MCP 默认只注册 recall / memorize；checkpoint 需要的 snapshot_memory /
restore_memory 由服务端 --enable-admin 开放，未开放时门面明确报 MemoryAdminDisabled。
快照传 zip 内容与 sha256，不共享文件路径；客户端 memory_root 只管本地 snapshots，
服务端根由 --memory-root 指定。原始 zip 上限 256 MiB，不安全条目由 MemoryCapability
在删除前统一拒绝，两种模式一致。管理面契约见 docs/mcp/memory-admin-spec.md。

**分层原则（三条）：**

1. **memory 只保管 harness 交给它的数据结构与索引、按键原样读写**；"发生了什么、影响了谁"
   这类语义判定（交互判定、受影响对象计算）由 harness 完成后以数据的形式交给它
   ——memory 不理解游戏，只理解键和记录。
2. **`brain` / `memory` / `trace` / `world` 一律按"独立第三方模块"对待**：各自只对外暴露
   一个 Port（`BrainPort` / `MemoryStorePort` / `TracePort` / `WorldPort`），契约收裸字段，
   不认识本项目任何 `*Req` 信封（信封是"某一跳"的概念，只存在于 `schemas/harness/`）。
   模块之间**只经门面层交换数据**——`direct/` / `mcpclient/` 的各 tool 认识两边的形状，双向转换只在那里做。
   允许**冗余类对象**（同一结构两边各声明一份、字段同构但互不引用），换来两边独立演进。
   *为什么*：这是"mock 能无痛换真实实现"和"模块能整体拷走复用"的机械保证。

3. **`task_memory` / `episode_memory` 是派生物，不是第二份事实。** 记忆阶梯是
   act（一键）→ task（一个 task）→ episode（一局）。上两级的**正文**是下一级全部记录
   连同 verify 正/负标注的蒸馏结果（可重建、可丢弃）；**来源章**（id / `goal` /
   步数 / `termination`，`success` 由 `termination` 推出）由 harness 从 state 盖上，与正文无关。
   来源章记机器判定；人审推翻只改目标表 / 任务表（`overturned`），**定案以表为准**。
   涉及"必须为真"的判断（成没成、走了几步）一律读来源章或更原始的记录，
   **不许从正文叙述里反推**。
   *为什么*：派生视图一旦被当成事实来源，蒸馏时的任何失真会静默跨局传播；反过来
   定清楚了，"重蒸"才是安全操作——原料一直在，产物随时可换。

一个模块超过 300 行就拆。一个函数超过 50 行就拆。

## 五、编排：LangGraph

- 循环用 `StateGraph` 承载，**不手写 while 循环**。
- **三张图各有一个状态载体**（都是 Pydantic 模型，字段有明确类型）：run 图用
  `harness/run/run_state.py::RunState`，episode 图用
  `harness/episode/episode_state.py::EpisodeRunState`，task 图用
  `harness/task/task_state.py::TaskState`。没有共用的"总状态"；层间只经交界契约
  （`schemas/harness/domain/{episode_io,task_io}.py`）传值。
- **每层只有 perceive 取帧、读记忆**：perceive 吸收下层结算 → 取帧（三层统一使用不调模型的 `perceive_task` 内存观测）→ 读直属下一级的记忆与世界事实；其余各格只用 perceive 装好的上下文。入口不取帧，
  上层不向下层传帧。
- **只存 `termination`**：`done` / `success` 是由它推出的只读属性（`Settled`），不另存一份。
- 节点函数是纯函数形态：`(state) -> state 增量`，副作用只允许发生在工具调用节点。
- **LangGraph 只管循环调度与状态传递。** 记忆层、状态表、值回填一律自己实现，
  不用 LangChain 的 Memory / Agent / Tool 封装。
  *为什么*：这些是本项目的原创部分，套框架抽象会讲不清楚也调不动。

## 六、LLM 与输出格式

- 本阶段已有真实 provider，**各自住在消费它的模块里**（`providers/` 包已解散）：
  `QwenProvider`（DashScope，语言+视觉两用）、`ArkProvider`（火山方舟/豆包，
  型号名必须带日期后缀）、`DeepSeekProvider`（DeepSeek 官方 API）、
  `ClaudeProvider`（Anthropic 原生 Messages API，`claude-` 前缀）、
  `OpenAIProvider`（OpenAI Chat Completions，`gpt-` 前缀）住
  `brain/providers.py`；`LocalEmbeddingProvider` / `LocalRerankerProvider`（本地向量化与重排）
  住 `memory/fastembed_text.py` / `memory/fastembed_reranker.py`。
  它们通过**四个 Protocol** 接入：`LLMProvider` / `JudgeProvider`
  （`brain/interface`；`JudgeProvider.describe()` 保留多模态图片输入）、
  `EmbeddingProviderPort` / `RerankerProviderPort`（`memory/`）。**brain 的四个 provider 由
  `brain/build_llm_providers.py` 的 `build_llm_providers(config)` +
  `BrainTool.build(links=…, …)`（链路型号与超参取自 `AppConfig.models`）组装**
  ——哪个技能接哪家厂商是 brain 的接线知识；`BrainLlmConfig` 由
  `BrainTool.build()` 内部构造（签名收裸字段，装配点因此不必
  import 任何 brain 名字）。world 只读模拟器内存，不调用模型；**memory 只经 MCP：
  `MemoryTool.build(memory_server_url=…, memory_root=…)`（地址必填，
  `memory_root` 只是客户端快照根）**；
  另两个同形工厂是 `GameTools.build(rom, …)` 与
  `TraceTool.build(run_id=…, trace_root=…)`。
  **所有工厂全在 tool 层，装配点一个都不越过**——它只递配置节里的型号名 / 路径这类字段。
  reviewer 进程仍单独启动（`python -m pokemon_agent.reviewer --config …`），与主进程读同一份配置；
  memory server 同样接受 `--config`。
  代码里**不许出现任何直连模型 SDK 的调用**——直连只发生在
  `brain/providers.py` 和 `memory/fastembed_*.py` 这几个实现文件里。
- **prompt 是规则，入参是素材——不互相替代，同一东西绝不两处传。** "怎么判、怎么想、
  怎么规划"全在 prompt 里（调用方组装、模块原样拿去问模型）；"判什么、想什么"才是入参。
  所以一个方法要么在 prompt 里给、要么当参数传，**不许两边都放**（论据、`history` 这些
  就是这样去掉的）。**模板跟着"拥有这次调用的那一方"走**：harness 发起的链路统一由
  `prompt/` 的 `PromptGateway` 按注册表版本渲染；world 不持有 prompt。
- 动作选择输出用 **Pydantic schema**（`Action` / `ActionSegment`）解析。
- **解析失败要重试并计数**，重试次数与失败计数进 trace。不许静默吞掉解析错误。
  重试循环住在 **tool 层**（`BrainTool.choose` / `BrainTool.plan`）——拼重试纠正说明是
  "拥有这次调用"的那层的事；账走 `resp.calls`（成功）或异常携带的 `exc.calls`（耗尽）。
  **每次尝试各落一条账**，所以"试了几次"= `len(calls)`，账里不另设"第几次"字段（0914 撤）。
- 约束解码（constrained decoding）留到接真实模型时再上，现在不做。

## 七、代码风格

- Python 3.11（`requires-python = ">=3.11"`；不是 3.10——`enum.StrEnum` 要 3.11 才有，
  `schemas/harness/domain/trace_kind.py` 用到）。
  所有公开函数、方法、Pydantic 字段**必须有类型注解**。
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

## 九、trace 约定（后面 replay / 成本统计全靠它）

**一条事件一个 json 文件、全平铺在落盘根下**：`tracelog/<uuid>.json`（缺省落盘根
= **进程启动目录**，`--trace-root` 可改）。**不按 run 分层、也没有 `events/` 这一层**
（0916 起）——run 的区分靠 `meta.run_id`。文件名是
**时间递增的 uuid**（前 48 位是毫秒时间戳），但**顺序不认文件名**——排序的真源是
内容里的 `(ended_at, seq)`（同刻按 append 序决胜，uuid 只是标识；文件名只保证不撞名、让 `ls` 大致按时间排）。
**没有内存事件镜像**：磁盘账本（`TraceToolPort.read_events`）是唯一真相，
读的人直接读它（`review` 节点的审核材料就走这里）。

**读哪一批由 `meta` 的交集匹配回答**：`read_events(meta={…})`——给的每个键都要
**相等**（AND-of-equalities，与 `MemoryStorePort.filter` 同一条语义，不支持 OR、
不支持大小比较）；`None` / 空 dict = 整个落盘根。落盘不按 run 分层之后，
`{"run_id": …}` 是切片的主键，`{"run_id": …, "episode_id": …}` 就是"这一局"。

每条事件八个字段（`schemas/harness/domain/trace_event.py::TraceEvent`，与
`trace/datastore/event.py::_Event` 逐字段对齐——**没有编译器保护，改一处必须同步另一处**）：

| 字段 | 说明 |
|---|---|
| `uuid` | 本次事件的唯一标识，**与文件名同值**。落盘那一刻由存储方盖上 |
| `seq` | 进程内 append 的**单调序号**（双后端共享、重启置零、不持久化）：**同刻 `ended_at` 的决胜键**。由存储实现在落盘时取号，调用方不传 |
| `kind` | **账名**（`schemas/harness/domain/trace_kind.py::TraceKind` 的值）。由 tool 层给，**渲染层不做任何翻译**——`req.kind` 一路落到这里 |
| `type` | 粗类，7 类（`trace/datastore/trace_event.py::EventType`，见 `docs/spec/DATAFLOW.md` 第四节「事件总表」）：`model_call` / `error` / `llm_outcome` / `view` / `act` / `memory_io` / `lifecycle`。**0903 收敛原则**：type 与"哪条产物"正交、数量极小；"哪个节点产出了什么"全部由 `kind` 回答（如 `think`/`judge_verdict`/`verify_verdict`、`read_*`/`write_*`、`do_action`/`get_action_space`） |
| `started_at` | Unix 时间戳（秒）：操作**真实开始**时刻。调用方记了就交，没记由存储实现补记账时刻（机械账 start=end=now——它没有时长语义） |
| `ended_at` | Unix 时间戳（秒）：操作**结束**时刻，**排序键的一半**（`(ended_at, seq)` 升序，算延迟与对齐外部日志也看它）。调用方不交则补记账时刻 |
| `meta` | **标签面的 JSON 字符串**：`{run_id, branch, source, episode_id, task_id, step}` 六件，**不多不少**。`run_id` 与 `branch`（执行线，未经恢复为 `main`）由 `TraceTool.append` 盖（`direct/trace/__init__.py::_stamp_meta`），`LocalTrace` 对 `meta` 只透传；另外四件由 harness 在 `req.meta` 里**一次交齐**，`TraceTool.append` 只核不拼。`source` = **这条账从哪个位置发出**（图上节点名，或图外入口名如 `run_entry.new_run`）。上层账的空位放本层 id：run 级账 `episode_id`/`task_id` 位放 run_id、`step` = 已派局数；episode 级账 `task_id` 位放 episode_id |
| `content` | **正文面的 JSON 字符串**。判据是"存在反函数"——能从这串字符无损还原出源记录的字段。**标量一律 `str()`、布尔一律小写 `true`/`false`**；本来就是结构化数据的那几处（`facts` / `sequence` / `verdicts` / 四本写账的正文）**直接放对象，不再 `json.dumps` 一次**（那是双重编码） |

- **0914 封套改造**：形状从九个字段收成六个，删了 `event_id`（唯一读方随
  `frame_png` 一起下线；排序改看 `ts`）、`schema_version`（零读方、两份副本要人工
  同步）、`frame_png`（**画面真源改成 `memory/step_memory/*.json` 的
  `before_frame`/`after_frame`**，事件不再自带图；`read_event(id)` 随之下线）、
  以及顶层 `run_id`/`episode_id`/`step`（搬进 `meta`）。
  **`kind` 与落盘的账名现在是同一个词**：此前 harness 那套派发键（`MEMORY_WRITE`…）
  与落盘账名（`write_step`…）两套名字靠一张翻译表连着，已整个删掉。
- **0927 双时刻改造 + 0928 325 `seq` 决胜键**：`ts` 拆成 `started_at`/`ended_at`（操作
  真实起止；调用方没记的账补记账时刻），随后 `seq`（进程内 append 的单调序号）进封套，
  排序从 `(ts, uuid)` 改成 `(ended_at, seq)`——同刻按 append 序决胜，uuid 退化为纯标识。
  旧格式缺 `seq` 的账解析失败、被扫盘跳过（**不兼容旧账**，2026-09-28 拍板）；字段数
  从六个变成上面八个。
- **0913 晚结构体瘦身**：更早还删过 `phase`（值恒等于 `type`）、`source`
  （生产者维度下线；**"谁发的"这一维 0914 改由 `meta.source` 回答**——那是
  "发送位置"，与"链路"不是一回事）、`valid`（恢复链已删，新写入恒真）。
- trace 是**追加写的事件序列**，不是可变状态快照——但这说的是 trace 自身的写入
  方式，不是 checkpoint 的存储形态。详见 `docs/ROADMAP.md` 第 16 条。
- 本阶段 `LocalTrace`（一条事件一个 json）就够，但接口按"能落盘、能重放"设计。

## 十、测试

规则见「可读性与可维护性 / 5. 测试是用法示范」。工具与硬性要求：

- `pytest`。目录按 **模块 → 功能** 两级镜像被测包：`tests/<module>/[<feature>/]test_<name>.py`（`<module>` 与 `pokemon_agent/` 下的包同名，跨模块的端到端放 `tests/integration/`；文件名全仓唯一，不靠目录区分）。共享夹具 `_fake_run.py` / `_fake_langfuse.py` / `_harness_fixtures/` / `_doubles/` 留在 `tests/` 根，经 `pyproject.toml` 的 `pythonpath` 直接 import；测试文件之间不互相 import，共用的替身放 `_doubles/`。慢测试标 `@pytest.mark.slow`，默认不跑；**不要用 `-m` 覆盖默认选项去跑它们**，需要时在本地临时去掉文件里的 `skip` 标记（现有慢测试 `tests/harness/checkpoint/test_checkpoint_restore.py` 已加硬 `skip`，不提交这种临时改动）。
- 必须存在的两个：**FakeLLM 跑完整 ReAct 循环且结果确定可复现**；
  **大脑在给定观测下选出预期动作**。
- 测试不许连网、不许调真实模型、不许依赖时间戳精确值。

> ⚠ **现状（2026-09-15 核实）**：`tests/` 下 13 个文件、104 个测试函数，**"必须存在的两个"一条都还没有**——
> 现有全是单元/契约级（渲染、落盘、prompt、状态访问器、图终止），没有 `FakeLLM + MockWorld`
> 跑完整 episode 的那一篇。这是**已登记的技术债**，不是规范改动；端到端那条目前靠
> `experiment/real_check/` 的四个真机维度顶着（见 `docs/spec/experiment/SPEC.md`）。

> ⚠ **现状（2026-09-15 核实）**：`scripts/` 下两个机械核对脚本**已不在仓库**——
> `check_graph_phases.py`（抽 `add_node` 的字面量与观测台相位表逐条比对、核对"节点名 = 实现
> 文件名"、`Runtime[...]` 的类型参数、`EpisodeInput`/`EpisodeOutput` 两侧键）与
> `check_imports.py`（全仓 import 守卫）。**前者守的那几条现在没有可执行的守卫**，只能靠
> `harness/` 的书写纪律（相关 docstring 已改成"曾经有"的措辞）。`scripts/` 下现存的自包含
> 检查只有 `check_trace_self_contained.py` 与 `check_world_self_contained.py`（两个都还在）。

## 十一、这个阶段明确不做

状态表在线归并（机制一）、MC 回填（机制三）、skill library（机制二）、沙箱。

**别提前做。** 但接口要留得住：设计任何抽象时问一句"机制一接进来时这里要改吗"，
要改就说明抽象错了。

## 十二、schemas：信封与接口模型命名（2026-09-10 定稿）

**分包形态**：产出的模块各自一个包、各自一个统一出口（`harness` /
`world` / `memory` / `trace`）。**`schemas/frontend/` 已于 0914 控制台改造整个删除**
——那套信封是给观测台前端用的（`FromFrontendToRunHarnessSubmitEditReq` 的整栈
原子替换）；观测台已移出仓库、控制台交互不走前端信封。**schemas 侧不再有 `providers` 子包**——它 0913 深夜十一
随代码层 `pokemon_agent/providers/` 一起解散：四封信（`LlmComplete*`/`VisionDescribe*`）
已是 **brain 的内部协议**，随 provider 搬进 `brain/schemas/`，图片通道供判定器等使用。包内按种类落到
`communication/` `domain/` `datastore/`。schemas 侧**不给 tool 门面单开子包**——
`direct/interface/` 四张门面协议（`GameToolPort` / `MemoryToolPort` / `BrainToolPort` /
`TraceToolPort`；存档那一张 `CheckpointToolPort` 已解散——存档归 harness 自己的状态模型），
harness 经门面调模块的架构不变。

**`schemas/review_backend/communication/`** 与 **`schemas/agent_reviewer/communication/`** 是 Web Reviewer / Agent Reviewer 这套跨进程 WS 转发层的信封——跳 B（后端↔前端 `/ui`）、跳 C（后端↔agent 独立进程，地址走 `.env` 的 `AGENT_REVIEWER_URL`），与跳 A（`schemas/harness/communication/`，harness↔后端 `/harness`）同形：都带 `msg` 标签、`model_dump_json()` 走 WS 文本帧；`ProposedAnswer` 单源定义在 `review_backend/communication/`，跳 B `proposal` 与跳 C `proposal` 共用同一模型；`FromFrontendToReviewBackendAnswerReq.by` 字面量含 `human`/`agent`/`timeout`，`FromReviewBackendToFrontendAskReq.deadline` 为 `float | None`（人模式传 `None`，AI 模式后端填倒计时）。它们**不属于铁律 1 的「Harness↔门面」那一跳**，是 harness 之外的独立跨进程转发层（后端只做无状态转发，不持有 transcript）。

1. **信封 = 我们自己的模块间契约**，命名 `From[模块A]To[模块B][函数名][Req/Resp]`，
   **两半都放 A 处（发起方）**。强制适用范围是 **Harness ↔ 各门面**这一跳。
   **外壳（experiment）→ Harness 这条边不包装**：外壳不是我们的模块，
   入参与返回值都走裸字段——`run(run_id, goals)` 返回
   `(outcomes, total, succeeded, success_rate)`，同款。
   注意别把这条推到记账层：**信封该内嵌模型就内嵌模型**——RUN_END 里的
   `RunResp` 由 `close()` 内部组装，跟 `run()` 返回什么无关（第 5 条）。
   第一跳（调用方 → 模块门面）永远是信封，**门面上的每个方法都算**——
   `GameToolPort` / `MemoryToolPort` / `BrainToolPort` / `TraceToolPort` 四张门面
   （代码在 `mcpclient/game_tools.py` / `memory_tool.py` / `brain_tool.py` / `trace/`）。
   有入参就有 Req，返回结构化载荷就有 Resp；返回 None 的没有 Resp
   （`FromHarnessToGameToolResetReq` 是先例——`reset()` 返回 `None`）。
2. **模块对外的接口模型用裸名**，不带 From/To（brain 的 `Action` / `RunPlan`、
   `brain/schemas/completion.py` 的 `LlmCompleteReq`、world 的 `TaskPerceived`、
   harness 的 `RunResp`）——因为发起方可能换人
   （今天 harness，明天第三方），From/To 前缀是赌一个注定被换掉的名字。
   **第二跳（门面 → 具体模块）走裸参数、返回模块自己的类型**，不造信封也不新建模型。
3. **豁免登记**：**当前为空**。
   - 原第一条豁免（`RunInteraction` 直读——三槽共享观察面）**已随控制台改造整个删除**
     （0914）：槽机制是观测台的配套件（写入方与读取方不在同一调用栈），
     控制台里人就在图的调用栈上，取而代之的是 `harness/interface/reviewer.py`
     的 `Reviewer`（插话 + 审）与 `planner.py` 的 `Planner`，两个都由装配点
     `build.py` 注入 `HarnessDeps`——走的是正常的依赖注入，不是"直读共享面"。
   - 原第二条豁免（`TracePort.cursor` 的零参标量读取）随恢复链一起删了。
4. **domain 实体按产出方归属**；**跨包引用只允许向下**，登记如下：
   - **`schemas` 侧的真实出边只有两处**（0915 用 AST 核过）：`schemas.harness.domain.goal_entry`
     → `brain`（`GoalEntry` 要内嵌 brain 的 `Task`），以及 `schemas.harness.communication/**`
     → `world` / `brain.interface`（跨层信封要内嵌两边的形状）。
     方向永远是"向下取形状"，反向不许；**`memory` 在这张图里出边为零**。
   - `trace` 是**最底层共用层**，任何包可引用（`TraceEvent` 进 plan 上下文），
     它自己零跨包引用。`providers`（代码层实现包）0913 已解散——
     实现按"谁消费"回了 `brain/providers.py` 与 `memory/fastembed_*.py`。
     `schemas/providers/` 也随之一并解散（0913 深夜十一）：四封信是 brain 的
     内部协议、随 provider 进了 `brain/schemas/`；图片请求与响应由 brain 自己声明。
     账（`ModelCall`）的归属见下一行。
   - **代码层 `brain` 的引用面（0915 用 AST 重算；P7 拆分后复核）**：**实现依赖只有门面层**，
     共 4 处 import：`direct/brain_tool.py` 3（`Brain`/`BrainPort`/`BrainLlmConfig`/
     `build_llm_providers` 一族，加 `brain.errors` 的 `AttemptFailed`/`ParseFailure`/
     `ProviderRejected`）、`mcpclient/game_tools.py` 1（`brain.errors.ProviderRejected`）。
     `build.py` 对 brain **零 import**（工厂全收在门面层）。其余包对 brain 的引用**一律是数据形状**
     （`Action`/`ActionSegment`/`Goal`/`Task`/`RunPlan`/
     `EpisodeSummary`/`StepVerifyVerdict`/七个结果袋），按 import 语句数共 **28 处**：
     `harness/**` 14、`schemas/**` 12、`direct/trace/render` 2（`direct/prompts` 已于 595
     删除；此处的 28 是 0915 的历史计数口径，未重算）。
     **形状引用不是实现依赖**，不违反本铁律（跨层信封必须能内嵌这些形状，见第 1 条）。
     *计数口径*：一条 `import` 语句算一处，不按导入的符号个数拆开——
     换口径要整段重算，别两处混用。
   - **代码层 `world` 的引用面（0913 夜审计；P7 拆分后复核）**：**实现依赖只有 `mcpclient/`**
     （`game_tools.py` 的 `GameTools.build()` 造 `PyBoyWorld`）。`build.py` 对 world **零 import**（0913 夜才收平
     ——它是四模块里最后一个补上工厂的）。其余包对 world 的引用**一律是数据形状**
     （`Observation`/`ActionSpace`/`Facts`/`PlaceInWorld` + 世界语义常量
     `BUTTON_FACING`/`FACING_STEP`/`INTERACT_KEY`/`DIRECTION_KEYS`），共 **12 处**
     （0915 复核，**以脚本输出为准**）：`harness/episode/**` 4、
     `schemas/harness/communication/**` 8。
     **形状引用不是实现依赖**，不违反本铁律——`rules.py` 里 `PlaceInWorld(...)`
     的**真构造**与 `harness` 构造 brain 的 `Goal`/`Task`/`Action`（6 处）同属这一类：
     **非 tool 侧可以持有、也可以构造模块的数据形状，但不许碰它的实现**。
     world 自己的出边为 **0**（`world → pokemon_agent.*` 外部 import 零；
     确定性观测与异常根 `WorldError` 由模块自己声明）。
     **不做双坐副本**：world 的形状里没有项目专属字段（对照 trace 的
     `TraceEvent`——里面寄居了 7 个项目字段，那才是必须拆的归属错位），
     按 P2 第三类"登记即可"。可执行核对：
     `python scripts/check_world_self_contained.py`（A 出边为零 / B 实现面只在
     `mcpclient/` / C 装配点零 import + 打印本注册表）。
   - **`ModelCall` 有两份归属、按"跨过哪道边界"分**：跨层信封那份住
     `schemas/harness/communication/ModelCall.py`（只有循环控制者产出，`BrainTool._adopt()`
     把 brain 交出来的账收编成这一份）；brain 方言那份住
     `brain/interface/domain/model_call.py`（`Brain` 七个方法自己产出、`BrainTool` 消费）。
     **两份按边界独立归属**；两份 `ModelCall` 也**都没有"第几次尝试"字段**
     （0914 跟进删——`with_attempt()` 盖章连同 provider 侧 `max_attempts` 一起撤了，
     **尝试次数 = `len(calls)`**，由账在重试链上的位置回答）——
     **搬运点唯一**（`direct/brain_tool.py::_adopt()`）。
   - 叶子包之间零引用、**永不反向**：被调方不许 import 发起方的包。
5. **反向依赖的正解是改归属，不是摊字段。** 0910 的现场教训：
   `FromHarnessToTraceToolAppendReq` 内嵌 run 结算，而结算当时叫
   `FromFrontendToRunHarnessRunResp`、归在 frontend 包——记账层要内嵌它就得反向
   import 前端包（实测还成了 `schemas.frontend ↔ schemas.harness` 的循环 import）。
   正解是认出**这个模型本来就不属于那条边**：五个字段全是
   `harness/run/run_entry.py::close()` 自己数出来的，跟谁发起这次 run 无关，
   所以按第 2 条改成裸名 `RunResp`
   归 harness（入参那半直接摊成裸字段，见第 1 条），trace 内嵌它就是同包引用。
   （`schemas/frontend/` 已于 0914 整个删除，那个循环 import 的来源不复存在；
   这条留作**判据的示范**——下次再遇到"记账层要内嵌某边的东西"，
   先问它到底属于哪条边。）
   **不要为了断依赖把结算摊成 `run_total`/`run_succeeded`/`run_success_rate` 这类裸字段**
   ——信封该内嵌模型就内嵌模型，摊平只是把归属错误藏进字段列表里。


## 测评任务收敛（2026-10-13）

九个公开任务登记在 `evals/registry.py`：三个 B 类（decode、memory_store_recall、world_script_execute）用 `python -m evals.<任务名>` 启动 DeepEval；六个 C 类（brain_choose、brain_plan、brain_decompose、brain_judge、brain_summary、agent_short_goal_run）用 `inspect eval evals/<任务名>/task.py`。choose、plan、decompose、judge、summary 五个独立脑能力评测统一由 Inspect AI 管理；`python -m evals.brain_choose` 同样转发给 Inspect。choose/plan/decompose 的参考是建议，允许多种合理动作、失败纠偏和等价拆分，由独立 AI 逐维给0..1质量分；动作能力、单步和预算等结构约束另列。judge 与既有真假标注比较准确率。summary 复用三层冻结原料，机械契约与 AI 五维质量、重大失真分开统计，整体质量按 task/episode/run 三层宏平均。

B 类每个状态一个 LLMTestCase，指标不调模型；缺标或无从判跳过，不进分母。decode 的显式空值照常计分。DeepEval 原生输出帧级通过率与逐指标 Average Score/Pass Rate/Total，默认只列失败，有失败退出 1。memory 逐记录计存储、逐查询计 Recall@k 与 MRR，后两者看 Average Score。world 分 code/truth 与 pass.<脚本名>，每例子进程保留 300 秒超时。

`agent_short_goal_run`、`world_script_execute` 与 `memory_store_recall` 的评测脚本会自行启动所需 MCP 服务；运行前不必手工启动服务或设置 `MCP_*_SERVER_URL`。若相应 URL 环境变量已设置，脚本会复用对应服务（调试用）。短目标评测按样本隔离 world / memory，world 脚本评测按用例隔离 world，memory 评测默认使用启用 admin 的临时空库；若复用已配置的 memory 服务，评测会先清空其数据。

任务代码集中在 evals/<任务名>/，文件多时使用 dataset/、solver/、scorer/、compare/ 子包；各任务的数据版本紧邻加载代码。共享 DeepEval 运行器与 world 装配在 evals/common/；evals/dataset/ 只保留共用 frames/、io.py、errors.py。旧 tasks/、solvers/、scorers/ 槽位目录已删除。AGENTS 与 CLAUDE 的本节保持同步。

`agent_short_goal_run` 的独立结果评分员由 `evals/config.json` 的 `evaluation_models.result_grader` 配置型号、地址、密钥环境变量名、温度、输出上限与超时；默认使用 DashScope 的 `qwen3.7-plus`，型号不得与被测四条链路中的任一型号相同。`grader_model` 缺省使用该配置，字符串 `none`（大小写不敏感）关闭独立评分，其他字符串只覆盖型号且仍检查独立性。`evaluation_models.test_text` 保持字符串，供独立脑能力评测使用。

真实模型测试使用配置型号。world 不调 LLM，memory 使用本地 embedding/reranker。harness_integrity 属于 tests 集成测试，不是公开评测任务。agent_short_goal_run 仍按最终机械结果、红线与独立模型结果评分；路径、步数与策略等仅用于诊断。
