# `pokemon_agent/interfaces/` 技术规格说明

## 0. 本模块的定位

`interfaces/` 是 Harness 与外界之间的"端口层"（ports/adapters 架构中的 ports）。这一层几乎全部由 `Protocol` 定义组成，方法体全部是 `...` 占位——**这是刻意的**：

- `Protocol` 是结构化类型（duck typing 的静态版本），不需要具体实现类显式继承它，只要方法签名匹配即可被 `runtime_checkable` 的 `isinstance()` 认出来。
- 这一层只规定"契约"（谁能拿它做什么、前置/后置条件、失败语义），不规定"怎么做"。真正的行为都在 `pokemon_agent/world/`、`pokemon_agent/tools/`、`pokemon_agent/brain/`、`pokemon_agent/providers/` 等实现模块里。
- 好处直接体现在文件里反复强调的一点：**上层（Harness、大脑）只认协议，不认具体类**。换模拟器、换模型供应商时，协议层一行不用改，Harness 和大脑也一行不用改。

模块文件一览：

| 文件 | 定义的协议/类型 | 一句话职责 |
|---|---|---|
| `world.py` | `WorldPort` | 世界本身能做什么（推进、观测） |
| `tools.py` | `GameToolPort`、`MemoryToolPort` | Harness 伸向环境和记忆的两只手 |
| `brain.py` | `BrainPort` | 所有需要 LLM 才能回答的问题 |
| `trace.py` | `TracePort` | 追加写的事件日志 |
| `llm.py` | `LLMProvider`、`Completion` | 纯文本模型的出口 |
| `vision.py` | `VisionProvider`、`VisionCompletion` | 视觉模型的出口 |

---

## 1. `world.py` —— `WorldPort`

> 模块顶部原话："harness 底下的那一层，**大脑看不到这个文件**。"

### 1.1 为什么和 `GameToolPort` 分开

- `GameToolPort` 回答的是"Harness 能拿世界做什么"，`WorldPort` 回答的是"世界本身能做什么"——**两者职责不同，变化速度也不同**。
- `GameTools`（`tools/game_tools.py` 的实现）用 `WorldPort` 来实现 `GameToolPort`：`GameTools` 是适配器，`WorldPort` 是它包装的下层端口。
- 当前唯一的实现是 `PyBoyWorld`（`pokemon_agent/world/pyboy_world.py`）。换模拟器时，**`GameToolPort` 和大脑一行都不用改**——这正是分层要买的收益。
- 这里没有动作掩码（masking）：掩码是 Harness 的策略,不是世界的能力。世界只回答"全部动作是什么"和"执行这个动作会怎样"，筛选可用子集是上层的事。

### 1.2 为什么 `reset`/`observe`/`inspect` 返回 `PerceptionResult` 而不是裸 `Observation`

感知的开销（token 数、延迟、模型原始输出）和被感知的那一帧，两个地方都放不下：

- 放不进 `Observation`：那是**大脑看的东西**，大脑不该知道 token 数；而且 `Observation` 是跨层契约，往里加字段等于改接口。
- 又必须进 trace：没有它，成本拆不开、读错的观测追查不到是哪一帧，阶段 3.2 拿 VLM 输出和真值对标也对不上号。

**历史方案（已废弃）**：曾经用一个 `drain_calls()` 方法 + 一个内部缓冲区 `self._pending_calls` 解决这个矛盾——产生调用记录的地方先攒到缓冲区，Harness 再单独调 `drain_calls()` 取走清空。这种"生产/消费分离、靠可变状态搭桥"的设计本身就是 bug 温床：缓冲区什么时候清、被谁清，两个方向都能出错。

**现方案**：`calls` 跟着 `Observation` 一起，作为 `PerceptionResult` 的返回值原样交出来——产生调用记录的地方直接 return 出去，一路跟着 `_perceive()` → `observe()` → `reset()`/`inspect()` 普通地往上传，不需要任何跨调用的状态。`step()` 同理，`calls` 挂在已有的 `ToolResult` 上,不必新开类型。不产生模型调用的世界，`calls` 返回空列表即可，这不是负担。

### 1.3 方法签名表

| 方法 | 签名 | 前置条件 | 后置条件 | 失败语义 |
|---|---|---|---|---|
| `reset` | `reset(self, task: Task) -> PerceptionResult` | `task.max_steps > 0` | 返回的 `result.observation.done` 为 `False`（`step` 由 Harness 盖章）；`result.calls` 是这次重置期间产生的模型调用记录（通常来自随后那次感知） | 未文档化 |
| `observe` | `observe(self) -> PerceptionResult` | 无 | 幂等，不推进世界；`result.calls` 非空当且仅当真的调了视觉模型，命中缓存时是空列表（**不是 None**） | 未文档化 |
| `inspect` | `inspect(self, focus: str) -> PerceptionResult` | `focus` 非空 | 世界不推进；答案并进观测的 facts；下一次 `step()` 之后自动失效（下一帧就过期）；`result.calls` 含这次细看产生的调用记录在前，随后内部再看一眼观测（通常命中缓存）产生的记录（若有）跟在后面 | **不抛异常**。细看是锦上添花，问不出来就把"没看清"记成答案——为它中断一局不划算 |
| `all_actions` | `all_actions(self) -> list[str]` | 无 | 非空，且内容在整个 episode 内不变；这是 masking 的全集,Harness 从中筛出当前可用子集 | 未文档化 |
| `last_frame_sha`（属性） | `@property last_frame_sha -> str` | 无 | 最近一次观测所依据的那一帧的哈希；没有"帧"概念的世界返回空串 | 用途：没有它,一条读错的观测无法追查是哪一帧,而那是查感知错误的起点 |
| `step` | `step(self, action: Action) -> ToolResult` | `action.name` 在 `all_actions()` 中；且当前 episode 未结束（`done` 为 `False`） | 若返回的 observation 非空，其 `step` 等于调用前的 `step + 1`；达成 task 成败判据或用满 `max_steps` 时 `observation.done` 为 `True`（**成败判定属于 world**——只有它知道游戏状态是否满足判据）；`result.calls` 含推进这一步期间产生的模型调用记录（通常来自推进后重新感知那一次），命中缓存时为空列表 | 动作合法但没成功走 `ok=False`，不抛异常；action 不在 `all_actions()` 中是**调用方的 bug**，由 `assert` 拦下 |

### 1.4 `observe` 与 `inspect` 的区别

不在"再看一次"，而在**问的是不同的问题**：`observe()` 按帧缓存，同一帧再调返回的字节完全一样，没有新信息；`inspect()` 是对同一帧问一个具体问题。

### 1.5 谁实现、谁消费

- **实现方**：`PyBoyWorld`（`pokemon_agent/world/pyboy_world.py`），当前唯一实现。
- **消费方**：`GameTools`（`pokemon_agent/tools/game_tools.py`）——它持有一个 `WorldPort`，用它实现 `GameToolPort`。**Harness 和大脑都不认识这个协议**，`WorldPort` 是纯粹的下层端口，只对工具适配层可见。

---

## 2. `tools.py` —— `GameToolPort` 与 `MemoryToolPort`

> 模块顶部原话："Harness 伸向环境和记忆的两只手，分开的。"

### 2.1 为什么是两个协议：完整历史

**以前**：只有一个 `ToolHost`（另外还有一个更小的 `ToolPort` 给大脑用）。"感知世界"和"记忆"混在同一个协议、同一个实现类（`GameTools`）里。

**现在的两点变化**：

1. **大脑不再持有任何工具实例。** `Brain.choose()` 需要的情景记忆现在由 Harness 先查好、当参数（`memories`）传进去（详见 `brain.py` 一节）。大脑不再有机会主动调用 `GameToolPort`/`MemoryToolPort` 的任何方法，因此**大脑看到的那个小协议 `ToolPort` 已经没有存在的必要**——大脑该看到什么，完全由 `choose()`/`judge()`/`reflect()` 的参数表决定,不再需要一个额外协议来兜底"它还能主动做什么"。
2. **拆成 `GameToolPort`/`MemoryToolPort` 两个协议而不是一个**，是因为它们的实现本来就该是两个不相关的类：`GameTools` 只碰 `WorldPort`，`MemoryTool` 只碰 `memory/` 包。揉进一个协议会让人误以为它们必须由同一个对象同时实现。`Harness.__init__` 现在收两个参数：`game: GameToolPort` 和 `memory: MemoryToolPort`。

### 2.2 `perceive` 是纯读，它不构成"一步"——踩过的坑

`perceive()` 曾经既是"给大脑看一眼"，又是"新的一步开始了"两种身份，而这两种身份对它的期待不一样——于是要靠"这一步我是不是已经记过 trace 了"这种运行时判断去调和，而这个判断本身就是 bug 的温床（**实测出现过步号回退、判定重复计费**）。

现在 `perceive()` 只是查询：不写 trace、不推进世界、不触发判定。**"一步"的边界由 Harness 定义**，只有两个地方会产出新的一步。

### 2.3 `known_objects` 现在由 Harness 拼，不是 `GameTools`

以前 `GameTools.perceive()` 会顺手把语义记忆的 `known_here()` 结果拼进 `facts["known_objects"]`——这要求 `GameTools` 持有一份记忆的引用，正是这次拆分要去掉的耦合。

现在：`GameToolPort.perceive()` 只管世界；`facts["known_objects"]` 由 `Harness._observe()` 在拿到 `game.perceive()` 结果之后，另外调 `memory.known_here(obs)` 拼上去。两个协议各管各的，**组合是 Harness 的活**。

### 2.4 模型调用记账不再靠 `drain_calls`（与 `world.py` 同一段历史的工具层版本）

`perceive`/`inspect`/`reset` 曾经返回裸的 `Observation`，模型调用记录另开一个 `drain_calls()` 方法、靠世界内部一个缓冲区攒着给 Harness 单独取——典型的"生产和消费分离，靠可变状态搭桥"，缓冲区清早清晚都能把账算错。

现在这三个方法改成返回 `PerceptionResult`（`observation` + `calls` 两个平行字段），`execute()` 的 `calls` 挂在已有的 `ToolResult` 上。调用记录跟着它产生的那次调用一起，作为普通返回值直接交给 Harness，不存在"drain 时机对不对"这一整类 bug。

### 2.5 `GameToolPort` 方法签名表

| 方法 | 签名 | 前置条件 | 后置条件 | 失败语义 |
|---|---|---|---|---|
| `perceive` | `perceive(self) -> PerceptionResult` | 无 | **幂等只读**：不推进世界、不写 trace、不触发判定；同一帧内多次调用不产生额外模型调用（实现方要在帧内缓存，感知是每步都要付钱的一项）；`result.calls` 是这次调用产生的模型调用记录，命中缓存时为空列表（**不是 None**）；返回的 `observation` 在同一帧内稳定，**除非期间调用过 `inspect()`**（会往 facts 加一条 `inspected`，这是刻意的，意味着"幂等"只对模型调用成立、对返回值不成立） | 未文档化 |
| `inspect` | `inspect(self, focus: str) -> PerceptionResult` | `focus` 非空；**没有具体问题就不该调它**——否则只是把同一帧原样再看一遍（`perceive()` 帧内缓存字节完全一样），不产生新信息，纯粹白烧一次调用 | 答案并进下一次 `perceive()` 的 facts；`execute()` 之后自动失效；`result.calls` 是这次细看产生的调用记录 | 不抛异常，把"没看清"写成答案 |
| `get_action_space` | `get_action_space(self) -> ActionSpace` | 无 | `names` 非空——走投无路的状态也必须至少给一个动作，空动作空间是工具层的 bug，不能让大脑处理；`intents` **不由这一层填**（能不能拆子目标取决于目标栈深度，那是循环的事，工具层只管按键） | 未文档化 |
| `execute` | `execute(self, action: Action) -> ToolResult` | `action.name` 属于**调用前最近一次** `get_action_space()` 的结果；实现方必须 `assert` 这点——大脑幻觉出不存在的动作要在这里就地爆炸，不能变成语义不明的模拟器错误 | `result.observation` 非空，是执行后的新观测；它的 `step` **还没有盖章**（盖章是 Harness 的事）；`result.calls` 是推进这一步期间产生的模型调用记录（通常来自推进后重新感知那一次），命中缓存时为空列表 | 未文档化（见前置条件的 assert） |
| `reset` | `reset(self, task: Task) -> PerceptionResult` | `task.max_steps > 0` | `result.observation.done` 为 `False`；`step` 未盖章（由 Harness 填 0）；`result.calls` 是这次重置期间产生的模型调用记录 | 未文档化 |
| `last_frame_sha`（属性） | `@property last_frame_sha -> str` | 无 | 最近一次观测所依据的那一帧的哈希，用于追查读错的观测出自哪一帧；没有"帧"概念的实现返回空串 | 无 |

### 2.6 `MemoryToolPort` 方法签名表

> 两类记忆分开暴露，因为读写语义不同：情景记忆按相似度/时间检索，语义记忆按坐标查。程序记忆（procedural）还没做，先不占位。

情景记忆（episodic）：

| 方法 | 签名 | 前置条件 | 后置条件 | 失败语义 |
|---|---|---|---|---|
| `query_episodic` | `query_episodic(self, query: str, limit: int = 5) -> list[MemoryEntry]` | `limit > 0` | 返回条数 `<= limit`；按相关性降序；**检索策略属于实现方**——调用方不知道也不该知道记忆从哪来、怎么排的 | 未文档化 |
| `recent` | `recent(self, episode_id: str, limit: int) -> list[MemoryEntry]` | `limit > 0` | 返回条数 `<= limit`；全部来自 `episode_id` 这一局；最新的在最后 | 未文档化 |
| `write_episodic` | `write_episodic(self, entry: MemoryEntry) -> None` | `entry.rationale` 非空——没有理由的经验取回来也没用，说不出当时为什么这么判断，也就无法检查那个判断现在还成不成立 | 无返回值 | 未文档化 |
| `episodic_size`（属性） | `@property episodic_size -> int` | 无 | 库里有多少条情景记忆；**A/B 实验的自变量之一**，要能被记进事件流 | 无 |

语义记忆（object）：

| 方法 | 签名 | 前置条件 | 后置条件 | 失败语义 |
|---|---|---|---|---|
| `known_here` | `known_here(self, obs: Observation) -> str` | 无 | `obs.place` 所在地图上已知的语义记忆渲染成的一段文字；`obs.place` 为 `None` 时返回空串；没有任何已知条目时也返回空串——调用方（Harness）据此决定要不要往 `facts["known_objects"]` 里塞东西 | 未文档化 |
| `see_objects` | `see_objects(self, obs: Observation, stamp: str) -> None` | **一步只调一次**——`stamp` 非空，调用方保证不会同一步调两次 | 把这一帧看到的地标全部记一遍 | 未文档化 |
| `note_step` | `note_step(self, before: Observation, action: Action, after: Observation) -> list[ObjectFact]` | `before`/`after` 都有 `place`；算不出确定的一格时（连按、原地转身、两个候选同时存在）**不记**，宁可漏记也不能记错格子 | 返回被更新的条目（可能为空） | 未文档化 |

### 2.7 谁实现、谁消费

- **`GameToolPort` 实现方**：`GameTools`（`pokemon_agent/tools/game_tools.py`），内部只持有 `WorldPort`,不碰任何记忆。
- **`MemoryToolPort` 实现方**：`MemoryTool`（`pokemon_agent/tools/memory_tool.py`），只碰 `memory/` 包，不碰世界。
- **消费方**：`Harness`（`pokemon_agent/harness/harness.py`）。`Harness.__init__` 收 `game: GameToolPort`、`memory: MemoryToolPort` 两个参数,是 Harness 唯一认识的两个协议——Harness 不认识 `GameTools`/`MemoryTool` 这些具体类，也不认识 `WorldPort`。

---

## 3. `brain.py` —— `BrainPort`

> 模块顶部原话："所有需要 LLM 才能回答的问题，都在这个文件里"。

### 3.1 划界原则

这条边界是按"错了会怎样"划的,和 `world/ram.py` 那条一致：

- 需要判断、会错、要记账、要标定 → `BrainPort`（模型）
- 照抄内存、格式化、计数、查表 → Tools / Harness（确定的）

### 3.2 大脑是被调用方，它不记账——历史演变

**上一版**：brain 自己写 `MODEL_CALL` / `THINK` / `ERROR` / `MEMORY_READ` 事件，harness 写 `ACT` / `MEMORY_WRITE` / `OBSERVE` / `EPISODE_*` 事件——于是"某类事件归谁写"要一条条记；而且为了让判定器碰不到自己的账，还给 `judge` 开了个不写 trace 的例外，即**用例外弥补一条不统一的规则**。

**现在**：三个方法（`choose`/`judge`/`reflect`）都**不收 `episode_id`、不收 `step`、不碰 `TracePort`**，而是把账（`ModelCall`）连同结果一起交出来，由 Harness 翻译成事件。规则只有一句：**谁控制循环，谁记账。** 大脑连 `episode_id` 都拿不到，它想影响自己在实验数据里的样子也没有入口。

### 3.3 三个方法，三条互不通气的链路

`choose` 和 `judge` **必须是两个模型、两份 prompt、两笔账**。让做决策的模型顺带回答"我成功了吗"就是**误差同源**：它读错画面 → 以为达成了 → 判成功，而且错得越离谱数字越好看。成功率是这个项目唯一要报的硬数字，**它不能由被评价者自己给出**。

所以 `judge` 拿不到决策者的任何说辞：拿不到 thought、拿不到候选动作、拿不到历史里那几步的 `rationale`。**这条不许放宽。**

`judge` **看得到**本局最近几步发生了什么（`history`）——那不是放宽，是补一个洞：证据可能在三步前那一帧的对话框里，而一条第 10 步才压进来的子目标，前 9 步根本没人问过它。**"发生过的事"和"它对那件事的主张"是两样东西**，只给前者——渲染时一律 `MemoryEntry.render(reason=False)`。

目标栈接进来之后多了一条同样要紧的规则：**只有栈底那一层决定 episode 成败。** 子目标是 agent 自己压的，如果它完成也能写 `success`，agent 就可以压一个"我已经到家了"的子目标让判定器判它完成——成功率变成它自己发的奖状。所以子目标判成完成只弹栈，`success` 只在栈底那条被判成时才写。

### 3.4 大脑不再持有任何工具/记忆实例

`choose()` 需要的情景记忆由 Harness 检索好，当参数 `memories` 传进去——和 `judge()` 的 `history` 是同一个道理：大脑该看到什么，完全由方法的参数表决定，不给它一个能自己去翻记忆库的通道。

早一版是大脑自己持有 `tools` 去调 `memory_query`——"大脑自己决定检索什么"听起来是给它自由度，实际效果是**记忆检索这件"循环控制的事"混进了大脑的构造函数**，而且这条通道再也没被用来做别的事。收回来之后 `Brain` 连一个 Protocol 类型的协作者都不用持有，**无状态这条铁律在类型层面更容易守住**。

### 3.5 实现方必须无状态

判据：**连续两次用相同参数调用，行为必须一致**。episode 的状态全在 Harness 手里，通过参数传进来。

### 3.6 方法签名表

| 方法 | 签名 | 前置条件 | 后置条件 | 失败语义 |
|---|---|---|---|---|
| `choose` | `choose(self, goals: list[Goal], obs: Observation, space: ActionSpace, memories: list[MemoryEntry]) -> Decision` | `space.names` 与 `space.intents` 非空、`goals` 非空、`obs.done` 为 `False`（空动作空间是 Tools 的 bug，大脑不为它兜底） | `decision.action` 非 `None` 时，其 `intent` 属于 `space.intents`，且为 `PRESS` 时 `name` 属于 `space.names`；`decision.calls` 至少一条 | **重试全部失败时返回 `action=None`，不抛异常**——那是一类要被统计的失败模式，不是"再试试就好"，而"这一局要不要因此终止"是 Harness 的判断，大脑只如实汇报；**模型调不通（网络、鉴权）仍然会抛**（与 `judge` 对照） |
| `judge` | `judge(self, goal: Goal, obs: Observation, history: Sequence[MemoryEntry] = ()) -> Verdict` | 无——哪怕 `obs` 是空的也要能回答（答案是"没完成"） | **永远返回 `Verdict`，不抛异常**；任何异常情况（解析失败、模型不回话、网络抖）一律判**没完成**；理由不对称：判成"完成"会立刻终止这一局且直接进实验数据，判成"没完成"只是多跑几步，下一步还有机会纠正，所以所有不确定都往"没完成"倒 | 见后置条件；这是与 `choose` 刻意不同的一点——判定器坏掉不该让一局崩掉,那会把一次本可标记为"判定失败"的事件变成一局丢失的数据；而决策模型真的调不通时，这一局本来就跑不下去，硬撑只会产出无意义的步骤 |
| `reflect` | `reflect(self, before: Observation, action: Action, after: Observation) -> MemoryEntry` | `action.rationale` 非空 | 返回的 entry 内容完整（看到什么 → 为什么 → 做了什么 → 变成什么）；`episode_id` 留空由 Harness 盖章（和 `Observation.step` 一个道理——大脑不知道自己在哪一局）；**方法自己不写库**（写库是状态变更,大脑无状态,由 Harness 落库,"谁改了记忆"永远只有一个答案） | 未文档化 |

补充：`judge` 中任务目标和子目标走**同一个方法**，只是 `goal` 从目标栈的不同层取——判定在两种粒度上是同一回事：拿着一句判据去看一帧画面。分成两个方法只会得到两份要各自标定的 prompt。区分哪一层是调用方的事（Harness 在 trace 里标 `depth`）。

### 3.7 谁实现、谁消费

- **实现方**：`Brain`（`pokemon_agent/brain/brain.py`）。
- **消费方**：`Harness`（`pokemon_agent/harness/harness.py`）——**Harness 不认识任何具体模型**，只认识 `BrainPort`。

---

## 4. `trace.py` —— `TracePort`

> 模块顶部原话："trace 是 replay / checkpoint / SSE 观测台 / 成本统计 / 失败聚合 / 实验归因的共同底座，所以它的语义是**追加写的事件日志**，而不是"记录一下方便调试"。"

### 4.1 设计原则

接口按"能落盘、能重放、能推流"设计：

- `append` 不返回事件本身而是返回 `event_id`，因为落盘实现要在这里分配序号。
- `replay` 带 `after_event_id`，是给 SSE 断线重连补发用的（对应 HTTP `Last-Event-ID` 语义）。

### 4.2 为什么没有删除/修改

`TracePort` 类本身声明："事件的追加与读取。**没有删除和修改**，这是刻意的。" （事件日志作为审计/重放/成本归因的底座，一旦允许改写历史，replay、成本统计、失败聚合都会失去可信的基准。）

### 4.3 为什么 `run_id` 不在参数里

**由实现方在构造时持有**：一次实验一个 trace 实例，每条事件都属于它，让调用方一遍遍传是纯噪音，还给传错留了空间。同理，`ts` 也由实现方填，不由调用方传——它们是 trace 的属性，不是业务参数。

### 4.4 方法签名表

| 方法 | 签名 | 前置条件 | 后置条件 | 失败语义 |
|---|---|---|---|---|
| `append` | `append(self, episode_id: str, step: int, type: EventType, source: Source, payload: dict[str, str] \| None = None) -> int` | `step >= 0` | 返回分配到的 `event_id`，严格大于此前任何一次 `append` 返回的值（实现方必须 `assert` 这条——**SSE 的断线补发完全依赖它**，一旦出现重复或回退，观测台会静默丢事件）；`source` 是必填的（成本要按感知/决策拆开，失败要归到具体某一层；做成必填而不是可选，是因为可选参数最终总会有人不填）；`ts` 与 `run_id` 由实现方填，调用方不传 | 未文档化 |
| `replay` | `replay(self, episode_id: str, after_event_id: int = -1) -> Iterable[TraceEvent]` | `after_event_id >= -1`（`-1` 表示从头开始） | 按 `event_id` 升序回放事件；返回的事件 `event_id` 严格递增，且全部 `> after_event_id` | 未文档化 |

### 4.5 谁实现、谁消费

- **实现方**：具体的落盘/内存实现（如 `pokemon_agent/mocks/mock_trace.py` 中的 mock 版本，以及生产环境下的落盘实现）。
- **消费方**：`Harness`（写事件的唯一入口，呼应 `brain.py` 中"谁控制循环，谁记账"的规则）；此外 replay / SSE 观测台 / 成本统计 / 失败聚合 / 实验归因等下游消费者也读它，如 `probe/echo_trace.py`。

---

## 5. `llm.py` —— `LLMProvider` / `Completion`

> 模块顶部原话："存在的意义：代码里**任何地方都不许直连模型 SDK**（CLAUDE.md 第六节）。"

当前唯一的实现是 `providers/dashscope.QwenText`，换模型只改装配处的一行。

### 5.1 `Completion`（数据类型，非协议）

| 字段 | 类型 | 说明 |
|---|---|---|
| `text` | `str` | 补全文本 |
| `prompt_tokens` | `int = 0` | 提示词 token 数 |
| `completion_tokens` | `int = 0` | 补全 token 数 |
| `truncated` | `bool = False` | 输出是否被 `max_tokens` 截断 |

把 token 数放进返回值而不是让调用方去查，是为了**成本统计能在调用点就地产出 trace**，不需要 LLM 实现和成本模块互相认识。

`truncated` 字段的必要性：**必须由 provider 给，不能让调用方猜**——调用方不知道 `max_tokens` 是多少，只能拿 `completion_tokens == 某个整数` 去猜，那是巧合不是判据。为什么值得单开一个字段：截断在下游表现为"JSON 少了个右括号"，和"模型不会写 JSON"长得一模一样，但**修法完全相反**——前者要调大 `max_tokens` 或让模型少说，后者要改 prompt 或上约束解码。混成一类 `ParseFailure`，统计里就永远看不见它。

### 5.2 `LLMProvider` 方法签名表

| 方法 | 签名 | 前置条件 | 后置条件 | 失败语义 |
|---|---|---|---|---|
| `complete` | `complete(self, prompt: str) -> Completion` | `prompt` 非空 | 返回的 `text` 可能是任意字符串（**包括不合法的 JSON**）——解析失败是预期内的运行时情况，由调用方处理，本方法不为格式负责 | 底层不可用时**抛异常，不返回空 Completion**——"调不通"和"调通了但输出没用"必须能被调用方区分开 |

### 5.3 为什么故意做得很薄——不放进这个接口的东西

- **重试**：属于调用方的策略（大脑要按解析失败重试，并计数进 trace），不是 provider 的事。
- **结构化输出 / 约束解码**：原型期用 Pydantic 解析 + 重试代替；真上约束解码时应当加一个**新方法**而不是改这个方法的语义。
- **对话历史**：大脑无状态（铁律 1），历史由调用方每次组装完整传入。

### 5.4 谁实现、谁消费

- **实现方**：`QwenText`（`pokemon_agent/providers/dashscope.py`）。
- **消费方**：`Brain`（`pokemon_agent/brain/brain.py`）——`choose`/`judge`/`reflect` 内部用它把 prompt 变成文本。

---

## 6. `vision.py` —— `VisionProvider` / `VisionCompletion`

### 6.1 为什么不并进 `LLMProvider`：四条理由，任何一条单独都够

1. **大脑不该有看图的能力。** `Observation` 的 docstring 写死了"原始画面不进这里"。`LLMProvider` 一旦长出图片参数，大脑手里就多了一个它不该有的口子。
2. **两条链路会选不同的模型。** 感知每步都调、任务简单（枚举内分类 + 按 schema 填字段），该用最便宜的档；决策要真推理。分成两个 Port 才能分别选型、分别换供应商。
3. **本项目自己定过这条规矩。** `LLMProvider` 的 docstring 写道："真上约束解码时应当加一个新方法而不是改这个方法的语义。" 加图片是同类情况，且更重。
4. **计费结构就是这么分的。** 决策走有资源包的文本模型，感知走带免费额度的廉价视觉模型。

和 `LLMProvider` 一样做得很薄：只负责"图片进、文本出"。**分类、schema 填充、类型判定都不在这里**——那些是感知层的事，换模型不该动它们。

### 6.2 `VisionCompletion`（数据类型，非协议）

| 字段 | 类型 | 说明 |
|---|---|---|
| `text` | `str` | 补全文本 |
| `input_tokens` | `int = 0` | 输入 token 数——**不是可选的记账信息，它是正确性的证据**：网关静默丢弃图片时,这个数会塌回纯文本的量级 |
| `output_tokens` | `int = 0` | 输出 token 数 |

### 6.3 `VisionProvider` 方法签名表

| 方法 | 签名 | 前置条件 | 后置条件 | 失败语义 |
|---|---|---|---|---|
| `describe` | `describe(self, image_png: bytes, prompt: str) -> VisionCompletion` | `image_png` 非空、`prompt` 非空 | 返回的 `text` 可能是任意字符串（**包括不合法的 JSON**）——解析是调用方的事，本方法不为格式负责，与 `LLMProvider.complete` 一致 | 底层不可用时抛异常，不返回空结果；**判定为图片未送达时必须抛 `ImageNotDelivered`，不能静默继续** |

### 6.4 关键设计点：图片未送达检测

**⚠️ 实现方必须校验图片确实被消费了。**

实测背景：DashScope 的 Anthropic 兼容端点会**接受**带图请求、**不报任何错**、返回一段读起来完全合理的描述——而图根本没传到模型，描述全是凭空编的。判据是 **token 数不是回答内容**：一张 2.4KB 的 PNG 真被处理时输入至少几百 token，实测却只比纯文本多了提示词那十几个。

这是最危险的一类失败：**不报错，只幻觉**。不校验就会得到一个"完全正常工作"的 agent，每一步观测都是假的，等基线实验和 A/B 跑完才发现全部作废。

校验形式由实现方定（token 下界是最便宜的一种），但**判定为未送达时必须抛 `ImageNotDelivered`，不能静默继续**。

### 6.5 谁实现、谁消费

- **实现方**：DashScope 视觉端点的适配器（`pokemon_agent/providers/dashscope.py` 中对应视觉模型的类）。
- **消费方**：感知链路（`GameTools`/`PyBoyWorld` 内部产生 `PerceptionResult` 的地方）——大脑本身**不消费**这个接口，正是 6.1 节要保证的边界。

---

## 7. 协议间的依赖关系总览

```
                         ┌────────────────────┐
                         │      Harness        │
                         │ （唯一的循环控制者） │
                         └──────────┬──────────┘
                 依赖四个协议，互不认识彼此的实现类
        ┌─────────────┬─────────────┼─────────────┬──────────────┐
        ▼             ▼             ▼             ▼              ▼
  GameToolPort  MemoryToolPort   BrainPort    TracePort     （直接用 memory.known_here
   (感知/执行/   (情景+语义记忆)  (choose/     (append/       拼 facts["known_objects"]，
    开局/溯源)                    judge/       replay)        组合逻辑在 Harness 里)
        │                          reflect)
        │ 实现方 GameTools 内部持有
        ▼
    WorldPort  ←── 实现方 PyBoyWorld
   (reset/observe/inspect/all_actions/step)

  Brain 内部持有：
    LLMProvider   (choose/judge/reflect 的文本补全，实现方 QwenText)
    VisionProvider (感知链路的图片补全，独立于 LLMProvider，
                     由 GameTools/PyBoyWorld 一侧使用，大脑不持有它)
```

要点：

- **`GameTools`（`tools/game_tools.py`）用 `WorldPort` 实现 `GameToolPort`**：`GameTools` 是适配器/组合层，`WorldPort` 是它内部依赖的下层端口。`WorldPort` 对 Harness 和大脑都不可见。
- **`MemoryTool`（`tools/memory_tool.py`）实现 `MemoryToolPort`**，只碰 `memory/` 包，与 `GameTools` 完全不相关——这正是拆成两个协议要保证的隔离。
- **`Harness` 只认识 `GameToolPort`、`MemoryToolPort`、`BrainPort`、`TracePort` 四个协议**，构造时收具体实现的实例，但类型层面只依赖协议。这四个协议是 Harness 与外部世界打交道的**全部**通道。
- **`Brain` 只认识 `LLMProvider` 和 `VisionProvider`**（严格说，`VisionProvider` 是感知链路用的，`Brain` 本身不持有它——大脑不该有看图能力，见 6.1）。`Brain` 不持有 `GameToolPort`/`MemoryToolPort` 的任何实例，这是 3.4 节明确拆掉的耦合。
- **`known_objects` 的拼接**发生在 `Harness._observe()` 里,是 `GameToolPort.perceive()` 结果和 `MemoryToolPort.known_here()` 结果的组合,不属于任何单一协议的方法体内,这体现了"组合是 Harness 的活"的原则。

## 8. 全局共通的设计模式

1. **`PerceptionResult`（`observation` + `calls`）取代了历史上的 `drain_calls()` + 内部缓冲区方案。** 这一模式在 `world.py` 和 `tools.py` 中重复出现，本质是同一次架构演进：把"生产/消费分离、靠可变状态搭桥"的设计换成"调用记录跟着它产生的那次调用一起、作为普通返回值直接交出"。
2. **"谁控制循环，谁记账"**：`brain.py`、`trace.py` 都体现这条规则——大脑、World、Tools 都不持有 `TracePort`，也不接收 `episode_id`/`step`，记账动作全部发生在 Harness 一侧。
3. **失败语义分层**：区分"调不通"（抛异常，如 `LLMProvider.complete`、`VisionProvider.describe`、`Brain.choose` 遇到网络/鉴权问题）和"调通了但没用/没完成"（不抛异常，返回带有失败语义的值，如 `judge` 永远返回 `Verdict`、`inspect` 不抛异常而是把"没看清"写成答案、`choose` 重试失败返回 `action=None`）。这条区分反复出现在多个协议里，是本模块的核心设计哲学之一。
4. **协议即最小可见面**：每个协议只暴露消费方真正需要的方法，且方法参数表决定了消费方能看到什么（例如 `judge` 拿不到 `choose` 的说辞、大脑拿不到检索策略的控制权）。这是"谁该知道什么"这一原则在类型系统层面的落地。
