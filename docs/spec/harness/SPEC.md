# Harness 技术规格说明

源文件：`pokemon_agent/harness/harness.py`

本规格文档基于源文件的实现与模块内嵌的设计说明（中文注释）整理而成，力求做到"仅凭本文档即可复现出与源码一致的图结构与事件流"。所有小节标题下均标注对应源码位置，便于对照。

---

## 1. 模块定位与设计哲学（模块顶部说明）

### 1.1 为什么叫 Harness——一次改名的历史

按模块顶部注释所述：以前叫 `harness` 的那个类，实际上是**工具层**（大脑怎么碰环境）；而真正在做控制循环的是 `graph/build.py`。旧名字掩盖了这个事实，导致"一步"这个概念**没有唯一的主人**——`world` 在数 step，旧 harness 在猜边界，图在决定什么时候算一轮，三方各自维护一份状态，最终需要"按步去重来对账"才能保持一致。

这次改名 + 重构之后，只保留两个角色：

- **`LoopState`** 拥有"这一局跑到哪了"。`step` 在这里盖章，别的角色只读不写。
- **`Harness`** 拥有生死判断与记账职责，**自己不持有任何状态字段**（`__init__` 里只挂了 `game`/`memory`/`brain`/`trace` 四个外部端口的引用和编译好的 `_graph`，没有可变的实例状态）。

### 1.2 唯一性规则：`LoopState` 拥有 step，Harness 无状态，只有 Harness 写 trace

这是贯穿全文件的核心约束，共三条：

1. **`LoopState` 拥有"这一局跑到哪了"**：`step`、`goals`、`succeeded` 等身份字段全部在 `LoopState` 里流转，不作为 `Harness` 的实例字段存在。
2. **`Harness` 本身无状态**：类文档字符串明确写明"它自己没有状态——状态全在 `LoopState` 里流"。
3. **Harness 是唯一写 trace 的人**：模块顶部注释强调"全项目 `trace.append` 只出现在这个文件里"。大脑（Brain）把账（`ModelCall`）连同结果一起交出来，由 Harness 统一翻译成事件；判定器（judge）碰不到自己的账，这不是特权设计，而是**所有大脑调用的共同处境**——即凡是要花钱调模型的组件，记账权一律收归 Harness。**"唯一写"不等于"唯一拼"**：`Harness` 只调 `self._trace.append(*trace_utils.xxx(...))`，把领域对象（`Observation`/`Action`/`Goal`/`ModelCall`……）翻译成 `append()` 需要的五元组这一步，委托给纯函数模块 `pokemon_agent/trace/utils.py`——`Harness` 自己不拼任何 `dict[str, str]` 字面量。这是"harness 只负责调度，不负责模块逻辑"这条原则在 trace 这一侧的落地：调用点（决定"这一步该不该记、记成哪类事件"）留在 Harness，组装点（决定"记的话该记成什么样"）搬到 `trace_utils`。

### 1.3 状态为什么全在 LoopState 里——判据是"会不会影响下一个 prompt"

模块注释记录了一次设计反思：早先按"活多久"来分状态——单步流转的进 `LoopState`，`episode_id`/`task`/`step`/`succeeded` 当作 `Harness` 的实例字段。理由是"图状态会被复制、合并、快照"，但这句话只对**活对象**（world / tools / brain / trace）成立，它们确实序列化不了；而 episode 的身份是**纯数据**，恰恰是 checkpoint 唯一需要的那部分。放在实例字段里，等于把"跑到哪了"存在了一个 checkpointer 看不见的地方——接上 LangGraph 的 checkpointer 也恢复不出第几步、在跑哪个任务。

于是现行判据统一为：**"它会不会影响下一个 prompt"**，而不是"它活多久"。据此，`LoopState` 收纳了一局的全部可序列化状态，活对象（`world`/`tools`/`brain`/`trace`）一个都不进来——它们作为 `Harness` 的构造参数由装配处注入。

### 1.4 光有 LoopState 还复现不了

模块注释特别指出，恢复目标是"恢复 state + 恢复模拟器存档 = 接着往下跑"，但按上面的判据，还缺两样：

- **记忆库**（`GameTools._memories`）：它进 prompt，但既不在 state 也不在存档里；恢复出来记忆是空的，下一个 prompt 就不一样。
- **`world._facing`**：朝向是从**我们自己的动作历史**推的，不是从 RAM 读的，所以 pyboy 的 save state 里没有它——但它进 `facts`、进 prompt，这个洞更隐蔽。

补法留给"阶段 2"的 `Checkpoint`：`LoopState` + 记忆库 + 模拟器存档 + world 的推导状态 + manifest（模型型号与 prompt sha，因为 prompt 改了，同一个 state 也复现不出来）。

同时区分了两个概念：
- **replay**：不调模型，从 trace 里按顺序取 `raw` 重新解析（用途：改了解析器之后离线重算，不花钱），只需要 trace。
- **resume**：接着跑，需要完整 checkpoint。

### 1.5 为什么还是 LangGraph 而不是 while

三段之间的转移条件是显式的边，将来往中间插节点（状态归并、值回填、权限确认、成本熔断）不需要改循环体。LangGraph 只承担循环调度与状态传递，记忆和状态表全部是自研实现。

### 1.6 还没做的（模块注释原样保留）

"六件套只有 trace 一件"：缺权限确认、沙箱、成本上限、checkpoint、replay。

---

## 2. `LoopState`（pydantic Model）

定义于 `harness.py:154-202`，继承 `pydantic.BaseModel`，是"一局的**全部**可序列化状态"。

### 2.1 分组方式

字段分两组，但两组都定义在同一个模型里——分组只是为了阅读者知道哪些跨步、哪些不跨：

| 分组 | 字段 | 特点 |
|---|---|---|
| 身份 | `episode_id` / `task` / `step` / `succeeded` / `why` | 跨步存活，是 checkpoint 需要恢复的那部分 |
| 流转 | `observation` / `space` / `memories` / `action` / `press_result` / `outcome` | 单步内，从一个图节点传到下一个节点 |

### 2.2 完整字段表

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `episode_id` | `str` | 必填 | 这一局的标识，全局唯一。trace 按它分组 |
| `task` | `Task` | 必填 | 在跑哪个任务；目标、判据、步数上限都在里面 |
| `step` | `int` | `0` | 跑到第几步。**全项目只有这一个 step**。拆子目标（`push_goal`）和细看（`inspect`）**也算一步**——它们同样烧一次决策调用，混进同一个数里意味着 `max_steps` 是一道"总共允许它折腾多少轮"的闸 |
| `goals` | `list[Goal]` | `[]` | 目标栈。`goals[0]` 恒为任务目标，只有它决定 episode 成败；上面几层是 agent 自己拆的子目标，完成只弹栈，不写 `success` |
| `succeeded` | `bool` | `False` | 判定器说过达成了没有。一旦为真就不再问——结论不会反悔（"已经和母亲说过话了"不会因为多走一步就变回没说过） |
| `why` | `str` | `""` | 判成功时的依据。成功率是要报的数字，每个 `True` 都得说得出依据 |
| `observation` | `Observation \| None` | `None` | 当前这一步 `look` 拿到的观测 |
| `space` | `ActionSpace \| None` | `None` | 本步可选动作空间 |
| `memories` | `list[MemoryEntry]` | `[]` | `retrieve_memory` 查出来的、给这一步 `think` 用的情景记忆。图上单独一格——查什么、查几条是循环控制的决策，不该藏在 `think` 内部 |
| `action` | `Action \| None` | `None` | `think` 选出的动作 |
| `press_result` | `Observation \| None` | `None` | `press` 执行动作之后的新观测，交给紧跟着的 `remember` 去写记忆 |
| `outcome` | `EpisodeOutcome \| None` | `None` | episode 结束时的结果 |

### 2.3 `memories` 字段：生命周期与用途

`memories` 是最近才加入图状态的字段之一，专门承载 `retrieve_memory` 节点的输出。它的存在本身体现了一条设计决策："查什么、查几条"是循环控制层的决策，不该藏在 `think()` 内部的一行代码里；独立成节点后，`memories` 字段就是这一格交给下一格（`think`）的唯一产物。生命周期为单步：每一轮 `retrieve_memory` 都会重新查询并覆盖它，`think` 节点直接读取使用，不重新查询。

### 2.4 `press_result` 字段：生命周期与用途

`press_result` 是"`press` 执行动作之后的新观测"，专门用来把 `press` 节点产生的 after 观测**传给紧跟着的 `remember` 节点**去写记忆。源码注释明确指出其生命周期边界：

> 只在 `press → remember` 这一段之间有意义，`push_goal`/`inspect` 不产生它，`remember` 结束后被下一轮 `look` 写的新 `observation` 盖过去，不跨步存活。

即：它是一个"专用信使"字段，只在同一轮循环内、由 `press` 写入、由紧接着的 `remember` 读取一次，随后即被下一轮 `look` 产生的新 `observation` 覆盖（虽然 `press_result` 字段本身不会被显式清空，但它已经没有语义意义，下一次 `press` 会重新赋值）。

---

## 3. 图结构

定义于 `_compile()`（`harness.py:295-334`），文档字符串给出了顶层结构：

```
look → retrieve_memory → think → (press → remember | push_goal | inspect) → look
```

### 3.1 完整节点列表

| 节点名 | 对应方法 |
|---|---|
| `look` | `self._look` |
| `retrieve_memory` | `self._retrieve_memory` |
| `think` | `self._think` |
| `remember` | `self._remember` |
| `press`（= `Intent.PRESS.value`） | `self._press` |
| `push_goal`（= `Intent.PUSH_GOAL.value`） | `self._push_goal` |
| `inspect`（= `Intent.INSPECT.value`） | `self._inspect` |

`press`/`push_goal`/`inspect` 三个动作节点是通过 `_nodes()`（`harness.py:336-346`）这张 `Intent → 节点函数` 的映射表统一注册的：

```python
def _nodes(self) -> dict[Intent, Any]:
    return {
        Intent.PRESS: self._press,
        Intent.PUSH_GOAL: self._push_goal,
        Intent.INSPECT: self._inspect,
    }
```

源码注释说明了原因："散在 `add_node` 调用里的话，加了枚举值忘了加节点，症状是运行到一半 LangGraph 报'未知节点'——离病因隔了一层。" 写成表之后，漏一类会当场 `KeyError`，故障暴露得更早。

### 3.2 边

- **入口**：`graph.set_entry_point("look")`
- **`look` 的条件边**（经 `_route`）：
  - 若 `state.observation.done` 为真 → `END`
  - 否则 → `retrieve_memory`
  
  文档字符串强调："唯一的终止分支在 `look` 出口——看完才知道这一局还要不要继续。放在动作节点出口的话，'步数用尽'和'目标达成'要在三个地方各判一次。"

- **`retrieve_memory` → `think`**：固定边。
- **`think` 的条件边**（经 `_dispatch`，按 `state.action.intent.value` 分派）：`{i.value: i.value for i in Intent}`，即分派到 `press`/`push_goal`/`inspect` 三个节点之一。
- **动作节点回边**：
  - `press` → `remember`
  - `push_goal` → `look`
  - `inspect` → `look`
  
  代码实现为一个统一循环：
  ```python
  for intent in Intent:
      graph.add_edge(intent.value, "remember" if intent is Intent.PRESS else "look")
  ```
- **`remember` → `look`**：固定边，闭合循环。

### 3.3 ASCII 图

```
                         ┌───────────────────────────────────────────┐
                         │                                           │
                         ▼                                           │
                     ┌────────┐  obs.done?                           │
        entry ──────▶│  look  │──── True ──────▶ END                 │
                     └────┬───┘                                      │
                          │ False                                    │
                          ▼                                          │
                 ┌────────────────┐                                  │
                 │ retrieve_memory│                                  │
                 └────────┬────────┘                                 │
                          ▼                                          │
                     ┌─────────┐                                     │
                     │  think  │                                     │
                     └────┬────┘                                     │
             ┌────────────┼───────────────┐                          │
      intent=press  intent=push_goal  intent=inspect                 │
             ▼             │                │                        │
        ┌─────────┐        │                │                        │
        │  press  │        │                │                        │
        └────┬────┘        │                │                        │
             ▼              ▼                ▼                        │
       ┌───────────┐   ┌──────────┐    ┌──────────┐                  │
       │ remember  │   │push_goal │    │ inspect  │                  │
       └─────┬─────┘   └────┬─────┘    └────┬─────┘                  │
             └───────────────┴────────────────┴─────────────────────┘
                                (全部回到 look)
```

### 3.4 为什么 `retrieve_memory`/`remember` 被拆成独立的图节点

这是文件中最近一次改动，直接写在模块顶部说明和 `_compile()` 文档字符串中。核心动机：**图结构本身要能一眼看出两条规则**——

1. **每一步先查记忆再决策**：以前查记忆是 `_think()` 里的第一步，功能上没问题，但图上只看得到 `think`/`press` 两个方框，看不出"每一步都先查记忆再决策"这条规则。拆成 `retrieve_memory` 独立节点、并固定挂在 `look` 与 `think` 之间后，这条规则就是图的拓扑本身，不用看代码也看得出来。
2. **只有推进世界那一步才写记忆**：以前写记忆是 `_press()` 里的最后几步——一个 `press` 方框里同时塞了按键、情景记忆落库、语义记忆建档三件事，图上读不出这三件事的先后关系，也读不出"只有推进世界那一步才写记忆"这条规则（`push_goal`/`inspect` 世界没变，`after` 和 `before` 是同一帧，写进去就是一堆"结果：什么都没发生"，会稀释检索结果，所以它们不接 `remember` 这一格）。拆出来后，`remember` 只挂在 `press` 后面（`graph.add_edge(intent.value, "remember" if intent is Intent.PRESS else "look")`），从边的连法上就能看出"只有 press 之后才 remember"。

拆分带来的额外好处：以后想换检索/写入策略，改的是这一个节点，`think`/`press`/prompt 的形状都不用动。

### 3.5 分派放在边上而非节点内的 if

`_compile()` 文档字符串还强调了另一条设计原则："分派放在图的边上，不是某个节点里的 `if`。" 这样"agent 能做哪几类事"在图上一眼看得见，加一类新动作 = 加一个 `Intent` 枚举值 + 一个节点 + 一条边，`_think` 和 prompt 的形状都不用动。

---

## 4. 逐节点方法详解

### 4.1 `run()` —— 唯一的对外入口

见第 6 节详细展开。

### 4.2 `_begin(episode_id, task) -> LoopState`（`harness.py:257-291`）

**职责**：开一局：重置世界，写下边界，造出初始状态。**这里不观测**——观测是 `look` 的事，`look` 是图的入口。记忆**不清空**——跨任务复用经验正是要验证的东西。

**流程**：
1. `reset = self._game.reset(task)` 真实重置世界（这次重置里通常包含一次真实的开局感知）。
2. `self._trace.append(*trace_utils.episode_start(episode_id, task, memory_carried))` **先**写 `EPISODE_START` 事件（`Source.HARNESS`），payload 含 `task_id`/`goal`/`max_steps`/`memory_carried`（当前记忆库情景记忆条数）。注释解释了必要性：episode 的边界必须进事件流，否则光看日志分不出一次尝试从哪开始，更不知道它带了多少条记忆进来——而那正是 A/B 实验的自变量本身。
3. 对 `reset.calls` 里的每一条模型调用记录，**紧跟其后**当场 `for args in trace_utils.model_call(ep, 0, Source.PERCEPTION, call): self._trace.append(*args)`，**不留到下一次 `_observe()` 才补记**——注释强调"第一次 `look` 会命中这里刚建好的缓存，这个 episode 只会有这一次真正的开局感知"。`EPISODE_START` 排在这几条模型调用之前是刻意的：episode 的边界应该是这一局在事件流里出现的第一条事件，不是"先花了一次钱、才想起来这局开始了"——这条顺序只影响控制台/replay 里先看到什么，不影响"当场记账、不拖延"这条规则本身（两步都发生在同一次 `_begin()` 调用里）。
4. 构造并返回 `LoopState`，`goals` 初始化为单元素列表 `[Goal(goal=task.goal, criteria=task.success_criteria)]`——栈底是任务目标本身，"它永远在，也永远是成败的唯一依据"。

**读写 LoopState 字段**：不读（构造前），写：`episode_id`/`task`/`goals`（其余用默认值）。

**trace 事件**：`EPISODE_START`（先）；随后若干条 `MODEL_CALL`（+ 可能的 `ERROR`），均 step=0。

### 4.3 `_look(state) -> dict`（`harness.py:348-359`）

**职责**："每一步都从这里开始。"调用 `_observe(state)` 拿到 `(obs, goals, succeeded, why)`，据此更新 state。开局那一帧也走这里（它是图入口），所以"起点存档就已经满足判据"的 episode 会在第 0 步就被判出来，一步都不用走——注释指出不这样的话这类局会白跑满步数，成功率里少掉的正是最容易达成的那些。

**读写字段**：读 `state`（传给 `_observe`）；写 `observation`/`goals`/`succeeded`/`why`；若 `obs.done` 为真，额外写 `outcome`（调 `_outcome`）；否则额外写 `space`（调 `_space(goals)`）。

**trace 事件**：不直接写，全部委托给 `_observe`（及其调用的 `_judge`，二者都通过 `trace_utils` 拼 payload）与（若终止）`_outcome`。

### 4.4 `_space(goals) -> ActionSpace`（`harness.py:361-372`）

**职责**：按键选项由工具层给，**intent（能做哪几类动作）由这里给**。默认 `intents = [PRESS, INSPECT]`；若 `len(goals) < MAX_GOAL_DEPTH`，在中间插入 `PUSH_GOAL`。栈满了就把 `push_goal` 从可选项里摘掉，**不是靠 prompt 劝它别拆**。注释强调"说明和可选项必须一致，否则模型会去选一个用不了的东西，白花一轮再吃一条 IllegalAction"。

**读写字段**：读 `goals`（参数传入，非直接读 state）；不写 trace。

### 4.5 `_retrieve_memory(state) -> dict`（`harness.py`）

**职责**：这一步**全部的记忆读**都在这里发生——不只是情景记忆检索，`known_objects`（语义记忆，按坐标筛）和 `knowledge`（语义记忆，不筛的通用先验）也在这里读、折进返回的 `observation` 里。图上单独一格，是"查记忆"这个动作唯一的入口。

用**当前快照**（`Snapshot.of(state.observation).render()`）去查情景记忆，而不用 `obs.summary`——注释解释：记忆里存的是快照（位置/概况/地标/通行图），summary 是"你在野外"这种一句话，两边词汇几乎不重叠，字符打分会一条都选不中。

**流程**：
1. `memories = self._memory.query_episodic(..., limit=MEMORY_RECALL_LIMIT)`（`MEMORY_RECALL_LIMIT = 5`）。
2. `known = self._memory.known_here(obs)`；非空则 `obs = obs.model_copy(update={"facts": {**obs.facts, "known_objects": known}})`。
3. `knowledge = self._memory.knowledge_base()`；非空则同样折进 `obs.facts["knowledge"]`。
4. `self._trace.append(*trace_utils.memory_read(ep, step, memories, known, knowledge))`。

**为什么不放在 `_observe()`（`look` 节点）里**：`known_objects`/`knowledge` 是语义记忆的读，属于"查记忆"，不属于"看一眼"——`_observe()` 只该产出"这一帧模拟器/视觉模型实际给出的东西"。这不只是分类洁癖：早先把这两者塞进 `_observe()` 时，它们会在 `_judge()` 跑之前就出现在 `obs.facts` 里，被判定模型一起看到、白白花 token（`judge` 本不该看这类字段，见 `brain/SPEC.md` 的 `JUDGE_BLIND`）。现在 `_judge()` 在 `_observe()` 内部先跑完，`_retrieve_memory()` 是后一个图节点，判定模型天然看不到这两个字段。

`knowledge` **每次都重新读盘**（`MemoryTool.knowledge_base()` 不缓存），这是刻意的：要能一边跑 episode 一边改 `memory/knowledge/*.md`、不重启进程就生效。

**读写字段**：断言 `state.observation is not None`；读 `state.episode_id`/`state.observation`；写 `observation`（折了 `known_objects`/`knowledge` 之后的新副本）与 `memories`。

**trace 事件**：`MEMORY_READ`（`Source.DECISION`），payload 含 `count`（条数）、`refs`（`(episode_id, step)` 列表拼接），以及非空时的 `known_objects`/`knowledge`——三种读共用一条事件，因为它们都发生在同一个节点里，拆成三条反而让人以为它们发生在循环的不同位置。注释指出"检索发生在决策模型调用之前，事件顺序照实写——因果顺序，不是排版偏好"。

### 4.6 `_think(state) -> dict`（`harness.py:399-450`）

**职责**：调用大脑做决策，并把大脑交回的账（`ModelCall` 列表）翻译成事件。大脑一次 `choose()` 可能因解析失败重试多次，所以这里可能产出多组事件而非一条。

**流程**：
1. `decision = self._brain.choose(state.goals, state.observation, state.space, state.memories)`（**不重新查记忆**，直接用 `state.memories`——`MEMORY_READ` 已挪到 `retrieve_memory`，这里不再写）。
2. 断言 `decision.calls` 非空。
3. 对每条 `call`，`for args in trace_utils.model_call(ep, step, Source.DECISION, call): self._trace.append(*args)`——一条 `MODEL_CALL`，`call.error_kind` 非空时 `trace_utils.model_call` 会多吐一条 `ERROR`，Harness 只管把这个列表逐条 append，不自己判断"这次调用要不要额外记一条错误"。
4. 若 `decision.action is None`（重试用尽）：`self._trace.append(*trace_utils.decision_failed(ep, step, last))` 写一条 `ERROR`（`kind="MaxRetriesExceeded"`），然后 `raise MaxRetriesExceeded(...)`。注释强调"抛异常的是这里，不是大脑——大脑只汇报'一次都没解析出合法动作'，而'这一局是否因此终止'是循环的判断"。
5. 否则 `self._trace.append(*trace_utils.think(ep, step, decision.action, attempt=len(decision.calls)))`，payload 含 `thought`/`action`/`args`（json）/`rationale`（json）/`attempt`（重试次数）。`args` 必须记，"不记的话分不清'模型没给参数'和'给了但没显示'"；`rationale` 也记在这里，"不只依赖 `MEMORY_WRITE`——无记忆基线组不写记忆，那时 rationale 只剩这一处落点"。

**读写字段**：读 `observation`/`space`/`goals`/`memories`；写 `action`。

**trace 事件**：`MODEL_CALL`×N（跟随 `decision.calls`，经 `trace_utils.model_call`）；可能的 `ERROR`×失败次数（同一批 `trace_utils.model_call` 调用里带出来的）；成功时额外一条 `THINK`；失败耗尽时额外一条独立的 `ERROR`（`kind=MaxRetriesExceeded`，经 `trace_utils.decision_failed`）。

### 4.7 `_dispatch(state) -> str`（`harness.py:452-454`）

纯路由函数：断言 `state.action is not None`，返回 `state.action.intent.value`，供条件边分派到 `press`/`push_goal`/`inspect`。不写 trace，不改状态。

### 4.8 `_press(state) -> dict`（`harness.py:458-497`）

**职责**：按键，推进世界。**只管执行和账，不写记忆**（记忆写入移到紧跟着的 `_remember`）。**`step` 也不在这里加**——`press → remember` 是一个整体，加一次的地方在链路末尾 `_remember`，这样 `ACT`/`MEMORY_WRITE` 才落在同一个（第 n）步上。

**流程**：
1. `result = self._game.execute(action)`，断言 `result.observation is not None`。
2. 对 `result.calls`（执行期间通常是执行后重新感知产生的调用记录），逐条 `for args in trace_utils.model_call(ep, before.step, Source.PERCEPTION, call): self._trace.append(*args)`。注释强调"这一步的账当场记，不再拖到下一步 `_observe()` 才补记——calls 现在跟着 `execute()` 的返回值一起交出来，不用再靠 `drain_calls()` 那种隐式时机"。
3. `self._trace.append(*trace_utils.act(ep, before.step, action, message))` 写 `ACT` 事件（`Source.WORLD`），payload 含 `action`/`args`/`message`，step 用 `before.step`（即执行前的步号，也就是"这一步"）。
4. 返回 `{"press_result": result.observation}`——新观测暂不盖步号章（`step` 恒为 0，因为它还没被 `_observe` 处理过），但 `_remember` 只取其 `Snapshot`，与步号无关。

**读写字段**：读 `observation`/`action`；写 `press_result`（**不写 `step`**）。

**trace 事件**：`MODEL_CALL`×若干（跟随 `result.calls`）+ 可能的 `ERROR`；`ACT`×1。

### 4.9 `_remember(state) -> dict`（`harness.py:499-541`）

**职责**：把 `press` 刚推进的这一步写进记忆。图上单独一格，只跟在 `press` 后面。拆分动机同 3.4 节所述。

**流程**：
1. 断言 `observation`/`action`/`press_result` 均非 `None`。
2. `entry = self._brain.reflect(before, action, after).model_copy(update={"episode_id": ep})`——`episode_id` 在这里盖章，因为"大脑不知道自己在哪一局"。
3. `self._memory.write_episodic(entry)`，`self._trace.append(*trace_utils.memory_write(ep, before.step, entry))` 写 `MEMORY_WRITE` 事件（`Source.HARNESS`），payload 含 `key`/`content`（`entry.render()`），step 用 `before.step`。
4. `for note in self._memory.note_step(before, action, after): self._trace.append(*trace_utils.object_note(ep, before.step, note))` 逐条写 `OBJECT_NOTE` 事件（`Source.HARNESS`），payload 含 `key`（`note.landmark.place.key`）/`kind`/`content`。注释区分了两类记忆的作用域：情景记忆记"我在那种画面里选了什么"（作用域是一次经过），`OBJECT_NOTE` 记"地图39 x=2 y=3 那个人会说什么"（作用域是那一格，域内恒真、域会再现）；后者不需要模型判断——面朝哪一格由 `place + facing` 算出，两个输入都确定。
5. 返回 `{"step": state.step + 1}`——**`step + 1` 放在这条链路的末尾**，下一轮 `look` 写的 `OBSERVE` 才落在第 n+1 步上。若提前加一，事件流的步号会往回跳，读日志的人会把这条记忆读成下一步的。

**职责划分（press vs remember）**：`press` 负责"execute + 记执行期间的账 + 写 ACT"，`remember` 负责"reflect + 落库（情景记忆与语义记忆）+ step 自增"。二者通过 `press_result` 传递 after 观测：`press` 把 `execute()` 返回的新观测存进 `press_result`（不打步号章），`remember` 从 `state.press_result` 读出这份 after 观测用于 `reflect`/`note_step`。

**读写字段**：读 `observation`（作为 before）/`action`/`press_result`（作为 after）；写 `step`（自增）。

**trace 事件**：`MEMORY_WRITE`×1；`OBJECT_NOTE`×N（N 为 `note_step` 返回的条目数，可能为 0）。

### 4.10 `_push_goal(state) -> dict`（`harness.py:543-561`）

**职责**：把一个子目标压进栈。世界不动，但**仍然算一步**——因为它同样烧了一次决策调用，不算的话 `max_steps` 管不住"一直拆、从不走"这种局。

**流程**：断言 `len(state.goals) < MAX_GOAL_DEPTH`（`_space()` 应已把 `PUSH_GOAL` 从可选项摘掉，这里是防御性断言）；`self._trace.append(*trace_utils.goal_push(ep, step, depth, goal, rationale))` 写 `GOAL_PUSH` 事件（`Source.DECISION`），payload 含 `depth`（当前深度，压入前）/`goal`/`criteria`/`rationale`；返回 `{"goals": [*state.goals, goal], "step": state.step + 1}`。

**读写字段**：读 `observation`/`action`（取其 `goal`）/`goals`；写 `goals`（追加）/`step`（自增）。

**trace 事件**：`GOAL_PUSH`×1。

### 4.11 `_inspect(state) -> dict`（`harness.py:563-585`）

**职责**：对同一帧再问一次视觉模型。世界不动，但仍然算一步。注释指出 `INSPECT` 与 `OBSERVE` 是两个不同事件类型：后者每步必发，前者是大脑主动要的——混成一类就算不出"它多久要细看一次"，而那是判断这个动作值不值那次钱的依据。

**流程**：`result = self._game.inspect(focus)`；对 `result.calls` 逐条 `for args in trace_utils.model_call(ep, step, Source.PERCEPTION, call): self._trace.append(*args)`（错误类型标为 `InspectFailed`）；`self._trace.append(*trace_utils.inspect(ep, step, focus, answer))` 写 `INSPECT` 事件（`Source.PERCEPTION`），payload 含 `focus`/`answer`（最后一次调用的 `raw`）；返回 `{"step": state.step + 1}`。

**读写字段**：读 `observation`/`action`（取其 `focus`）；写 `step`（自增）。

**trace 事件**：`MODEL_CALL`×若干 + 可能 `ERROR`；`INSPECT`×1。

### 4.12 `_route(state) -> str`（`harness.py:587-589`）

纯路由：`END if state.observation.done else "retrieve_memory"`。挂在 `look` 的条件边上，是图上**唯一的终止分支**。不写 trace。

### 4.13 `_observe(state) -> tuple[Observation, list[Goal], bool, str]`（`harness.py:593-674`）

**职责**：全项目**唯一**产出 `Observation` 的地方；读一帧，盖上步号与终止判断，判一次成败，记进 trace。只有 `_look` 调用它，所以"一步恰好一次"——注释指出这正是这一版不再需要 `_traced_step`/`_judged_step` 那两个去重字段的原因：一步一次是调用图的形状本身保证的，不需要额外的去重逻辑。

**流程**：
1. `perceived = self._game.perceive()`，取 `raw = perceived.observation`。
2. `obs = raw.model_copy(update={"step": state.step, "done": raw.done or state.step >= state.task.max_steps})`——**盖步号**、**判"步数用尽"这一类终止**。
3. **`known_objects`/`knowledge` 不在这里拼**：它们是语义记忆的读，属于"查记忆"，不属于"看一眼"——放在 `_retrieve_memory()`（图上单独一格，紧跟在 `_observe()`/`_judge()` 之后）里，不放在这里。`_observe()` 只产出**这一帧模拟器/视觉模型实际给出的东西**。这是从"混进 `_observe()`"改过来的：那样会让 `knowledge` 在 `_judge()` 跑之前就出现在 `obs.facts` 里，被判定模型一起看到、白白花 token。
4. `self._memory.see_objects(obs, f"{state.episode_id}#{obs.step}")`——"看到的都建档，没互动过的也建"，放在这里是因为 `_observe()` 是唯一一步产出一次观测的地方，"seen 必须一步只加一次"；这一步写的是**语义记忆的写**（不是读），不受上面那条移动的影响。
5. 对 `perceived.calls` 逐条 `for args in trace_utils.model_call(ep, obs.step, Source.PERCEPTION, call): self._trace.append(*args)`（`ok != "True"` 时标 `PerceptionParseFailure`）。注释强调 `ok=False` 的调用要带 `error_kind`，否则"视觉模型输出解析失败"这一类永远不出现在失败模式分布里。
6. `self._trace.append(*trace_utils.observe(ep, obs, state.goals, self._game.last_frame_sha))` 写 `OBSERVE` 事件（`Source.PERCEPTION`），payload 含 `frame_sha`/`summary`/`scene`/`overlay`/`facts`（json）/**`goals`**（`trace_utils._render_goal_stack(state.goals)`，`trace_utils.observe` 内部调用）。
   - **`goals` 字段是判定弹栈之前的栈**：注释明确写道，"这里记的是这一帧被看到时的栈（judge 弹栈之前），因为 OBSERVE 必须先于本步的判定事件（因果顺序），判完之后的栈会在随后的 `GOAL_POP` 里体现"。即 `OBSERVE.payload["goals"]` 反映的是 `state.goals`（本步开始时、判定发生前的栈），不是判定之后可能已经弹出若干层的栈。加这个字段的动机：以前目标栈只在 `GOAL_PUSH`/`GOAL_POP` 事件里出现过一次，读日志的人拿不到"这一帧、这个决策，当时的栈到底长什么样"，只能靠回放前面所有 push/pop 事件手动重建。
7. `return self._judge(state, obs)`——把最终的判定工作委托给 `_judge`，返回值直接透传给 `_look`。

**读写字段**：读 `state.step`/`state.task`/`state.episode_id`/`state.goals`；不直接写 `LoopState`（返回元组由 `_look` 写回）。

**trace 事件顺序（因果顺序）**：`MODEL_CALL`(感知)×若干 + 可能的 `ERROR` → `OBSERVE`×1 → （委托给 `_judge`）`MODEL_CALL`(判定)×栈深 + 可能的 `ERROR` → `GOAL_POP`×0或多条。注释强调这个顺序不能反："先记产生这一帧观测的那几次感知调用，再记观测本身，最后才是基于它的判定。反过来记的话，拿事件流做 replay 的人会先看到结果、再看到产生它的原因。"

### 4.14 `trace_utils._render_goal_stack(goals) -> str`（私有函数，`pokemon_agent/trace/utils.py`，非 `Harness` 方法）

把目标栈压成一行字符串，塞进 trace payload：`" > ".join(f"[{depth}]{g.goal}" for depth, g in enumerate(goals))`，**栈顶（当前要做的）在最后**。注释说明这与 `Brain._render_goals`（多行、给模型读、栈顶在最上面）刻意不同——payload 值要求是字符串且不方便塞多行；一个格式是给人在日志里扫一眼查重复用的，一个是给模型逐行读的完整 prompt 片段，读者和用途不同，没必要共用一份格式。这个函数不在 `Harness` 里——它是 `trace_utils.observe()` 内部用的私有格式化辅助，只服务于"payload 该长什么样"，不属于 Harness 的调度逻辑。

### 4.15 `_judge(state, obs) -> tuple[...]`（`harness.py:688-780`）

**职责**：**每层各判一次（并发），最深的那条"已完成"连同它上面的全部出栈**——一条规则，没有特例。

**算法**：
1. **早退分支**：若 `state.succeeded` 已为真，直接返回 `(obs.model_copy(done=True, success=True), state.goals, True, state.why)`，不再判。注释解释这一分支在当前图内实际走不到（判成成功的那一步同时置了 `obs.done`，`_route` 直接走 END），但为 resume 场景保留：从一个 `succeeded=True` 的 checkpoint 恢复时，不打标记的话 `_look` 不出 outcome 会转而进 `think`，而那时 `goals` 已是空的（成功那一步清空了），`brain.choose` 的 `assert goals` 会当场崩掉。
2. 否则：`goals = list(state.goals)`（断言非空——"目标栈必须永远不为空"）；调 `_judge_all(episode_id, goals, obs)` 并发判每一层，得到 `verdicts`（按栈顺序）。
3. 逐条 `for args in trace_utils.judge_call(ep, step, depth, verdict.call): self._trace.append(*args)`——**判定的账单单独记**（`Source.JUDGE`），`depth` 塞进 payload 以区分"子目标判得多"和"任务判得多"两种粒度，否则子目标的判定成本会淹没任务本身判定成本这个数。`trace_utils.judge_call` 内部就是调 `trace_utils.model_call(..., Source.JUDGE, call.model_copy(update={"payload": {**call.payload, "depth": str(depth)}}))`，多包一层只是把"往 payload 塞 depth"这个判定专属的动作单独命名。
4. `done_at = next((d for d, v in enumerate(verdicts) if v.done), None)`——找**最深的**那条已完成的目标（`enumerate` 从栈底 depth=0 往上，取第一个 `done=True` 的索引，即最深完成的那层，因为 verdicts 与 goals 顺序一致，深度越大在数组里下标越大，`next` 找到的是最先出现、也是索引最大的那个 done——需配合 `goals` 定义：`goals[0]` 是栈底，往后越深）。
5. 若无一层完成（`done_at is None`）：`return obs, goals, False, ""`。
6. 若有：
   - **从上往下**（`range(len(goals)-1, done_at, -1)`）逐层写 `GOAL_POP`（`reason="superseded"`）——这些层"不是完成的，是失去意义的"，因为它们当初就是为完成的那一层拆出来的。从上往下记，使读日志的人看到的顺序与栈的物理形状一致：先作废最外层，再收掉完成的这一层。
   - 再写一条 `GOAL_POP`（`reason="done"`，`depth=done_at`）。
   - `remaining = goals[:done_at]`。
   - 若 `done_at == 0`（**栈底完成 = 任务完成**）：返回 `(obs.model_copy(done=True, success=True), remaining, True, why)`——**只有这一条路径写 success**。
   - 否则：返回 `(obs, remaining, False, "")`。

**为什么"最深的那条已完成"算法取代了"先判栈底再从栈顶往下弹"**：注释记录了迭代过程——早一版是两段特殊逻辑（先判栈底，再从栈顶往下弹），且**漏掉中间层**：栈是 `[任务, A, B]` 时只判了任务和 B，A 完成了也发现不了，于是继续做一个已经没有意义的 B。现行算法"每层各判一次"没有这个漏洞。

**为什么栈底那条必须每步都判**：它是其中一层，所以自动每步都判——这一点不能退，因为任务完全可能顺手完成（例如压着"走到门口"往那边走，路上母亲先说话了）。若只判栈顶，这类局会被系统性地记成 `max_steps_exceeded`，成功率被压低。

**为什么只有栈底那条写 success**：子目标是 agent 自己定的。如果它完成也能写 success，agent 就可以压一个"我已经到家了"的子目标让判定器判它完成——成功率变成 agent 自己发的奖状。落在代码里就是 `if depth == 0` 这一条判断（本文中体现为 `done_at == 0` 分支），不是一句注释。

**两个补充规则**：
- `obs.done` 不是跳过判定的理由——那里的 `done` 是"步数用尽"，而任务完全可能恰好在最后一步达成。
- 判过成功之后不再问——结论不会反悔。

**读写字段**：读 `state.succeeded`/`state.why`/`state.goals`/`state.episode_id`；不直接写 `LoopState`（通过返回元组，由 `_look` 写回 `observation`/`goals`/`succeeded`/`why`）。

**trace 事件**：`MODEL_CALL`(判定)×栈深（跟随 `verdicts`，经 `trace_utils.judge_call`）+ 可能的 `ERROR`；`GOAL_POP`×(出栈层数，0 到 栈深) 条（经 `trace_utils.goal_pop`）。

### 4.16 `_judge_all(episode_id, goals, obs) -> list[Verdict]`（`harness.py:782-822`）

**职责**：并发判每一层，**按栈的顺序返回**。

**流程**：`history = self._memory.recent(episode_id, JUDGE_HISTORY)`（`JUDGE_HISTORY = 3`，同一份历史发给每一层，不按层筛选——因为它落在同一步内这几次调用共享的 prompt 前缀里，重复的 input token 基本免费，按层裁剪反而会把前缀切碎）。若 `len(goals) == 1`，直接单次调用 `self._brain.judge(goals[0], obs, history)`；否则用 `ThreadPoolExecutor(max_workers=len(goals))` 并发 `pool.map` 调用每一层的 `judge`。

**为什么并发而非把整栈塞进一次调用**：注释给出两条理由——
1. **判定之间的隔离**：现在每条目标各判各的，模型看不到别的目标；合成一次会导致模型在不同目标间互相推理污染判断（如"子目标完成了，那任务应该也快了"）。
2. **可标定性**：单目标判定是干净的二分类 `(目标, 判据, 帧) → 0/1`，可拿人工标注算准确率；合成一次后输出是长度可变的向量，且同一份 prompt 在不同栈深下不是同一个东西，误差不再独立。

并发只省时间（`max` 而非 `sum`），token 的问题靠 prompt 的字段顺序解决：`judge_success.md` 把固定说明和画面放前面、目标放最后，同一步内几次调用共享一大段前缀，重复 input 基本免费。

**两个实现约束**：
1. **模型调用并发，写 trace 不并发**：`TracePort.append` 要分配单调的 `event_id`，多线程写会乱序甚至重号，而 SSE 断线补发完全依赖它——所以只并发拿结果，记账回到主线程按 `depth` 顺序做（体现在 `_judge` 里 `for depth, verdict in enumerate(verdicts)` 是串行循环）。
2. **不再有提前退出**：顺序版判到第一条完成的就停，能省几次调用；并发版全判——"用 token 换墙钟，这是这次改动明确选的那一边"。

**读写字段**：读 `goals`/`obs`（参数）；不写 `LoopState`，不写 trace（记账在调用方 `_judge` 里做）。

### 4.17 `trace_utils.model_call(episode_id, step, source, call) -> list[AppendArgs]`（`pokemon_agent/trace/utils.py`，不再是 `Harness` 方法）

**职责**：把一次模型调用（`ModelCall`）翻译成 trace 事件——"一次模型调用 → 一条 `MODEL_CALL`，失败的再补一条 `ERROR`"。**这曾经是 `Harness._record_call`**（直接 `self._trace.append(...)`），现在拆成一个不认识 `TracePort`、不做任何 I/O 的纯函数：输入 `ModelCall`，输出 `AppendArgs` 的 `list`（长度 1 或 2），调用方（`Harness`）自己逐条 `self._trace.append(*args)`。

**返回值构造**（等价逻辑）：
```python
events = [(episode_id, step, EventType.MODEL_CALL, source, call.payload)]
if call.error_kind:
    events.append((
        episode_id, step, EventType.ERROR, source,
        {"kind": call.error_kind, "reason": call.error,
         "attempt": call.payload.get("attempt", "")},
    ))
return events
```

**设计理由**：账单和失败模式是两件事——前者回答"花了多少钱"，后者回答"为什么没拿到东西"。混进一条里，按失败类型聚合时就得去解析 payload 里的字符串。拆成纯函数之后还多了一条好处：可以脱离 `TracePort`/`Harness` 单独单元测试——给一个 `ModelCall` 断言吐出来的 `list` 长什么样，不需要造一个假 `TracePort`。

**调用方**（全项目，均在 `Harness` 里，逐条 `self._trace.append(*args)`）：`_begin`（reset 的感知调用）、`_press`（执行期间的感知调用）、`_inspect`（inspect 的感知调用）、`_observe`（perceive 的感知调用）、`_think`（决策调用）、`_judge`（判定调用，经 `trace_utils.judge_call` 这个薄包装）。

### 4.18 `_outcome(state, obs, why) -> EpisodeOutcome`（`harness.py:842-861`）

**职责**：在 `_look` 判定 `obs.done` 为真时被调用，产出并记录本局最终结果。

**流程**：
1. 断言 `obs.done`。
2. 计算 `reason`：`"success"`（若 `obs.success`）/ `"max_steps_exceeded"`（若 `obs.step >= state.task.max_steps`）/ `"world_ended"`（其余情况，如窗口被关）。
3. 构造 `EpisodeOutcome(episode_id, task_id, success=obs.success, steps=obs.step, reason=reason)`。
4. `self._trace.append(*trace_utils.episode_end(episode_id, result, why))` 写 `EPISODE_END` 事件（`Source.HARNESS`），payload 含 `success`/`steps`/`reason`/`task_id`/`why`。注释强调"成功与否必须落进事件流，不记的话光看日志算不出成功率——而那是这个项目唯一的一组硬数字"；`why` 也要留档，"每一个 `True` 都得说得出依据"。
5. 返回 `result`。

**读写字段**：读 `state.episode_id`/`state.task`；不写 `LoopState`（`outcome` 由调用方 `_look` 写回）。

**trace 事件**：`EPISODE_END`×1。

---

## 5. 模型调用记账机制（全项目视角）

模块顶部说明中特别提到这是一处近期改动："账现在跟着 `PerceptionResult`/`ToolResult` 返回值走，不再靠 `drain_calls`。" 具体表现为：

- **`reset()`（`_begin`）**：`self._game.reset(task)` 返回的 `reset.calls`，在 `_begin` 里当场遍历记账（`Source.PERCEPTION`）。
- **`execute()`（`_press`）**：`self._game.execute(action)` 返回的 `result.calls`，在 `_press` 里当场记账（`Source.PERCEPTION`）。
- **`inspect()`（`_inspect`）**：`self._game.inspect(focus)` 返回的 `result.calls`，在 `_inspect` 里当场记账（`Source.PERCEPTION`）。
- **`perceive()`（`_observe`）**：`self._game.perceive()` 返回的 `perceived.calls`，在 `_observe` 里当场记账（`Source.PERCEPTION`）。注意由于 `perceive()` 按帧缓存，若 `_press` 刚感知过同一帧，这里 `result.calls` 通常是空列表，不产生额外 `MODEL_CALL`。
- **`choose()`（`_think`）**：`decision.calls`，在 `_think` 里记账（`Source.DECISION`）。
- **`judge()`（`_judge_all` → `_judge`）**：`verdict.call`，在 `_judge` 里记账（`Source.JUDGE`）。

旧机制（`drain_calls()`）的问题（据模块注释推断其被替代的原因）：那是一种"下次谁来取谁就顺手把上一步的账也记了"的隐式时机；新机制要求每个产生调用的接口把 `calls` 随返回值一起交出来，调用方在**当场**（同一个方法内）完成记账，不依赖"下一次谁来调用"这种隐式触发。这确保了账目与产生它的动作在同一个 trace 事件序列位置上，不会跨步错位。

---

## 6. `run()` 方法整体流程（`harness.py:224-255`）

`run(self, episode_id: str, task: Task) -> EpisodeOutcome` 是 `Harness` **对外唯一的入口**。

**前置条件**（用 `assert` 表达）：
- `episode_id` 非空字符串。
- `task.max_steps > 0`。

**后置条件**：trace 里恰好多一条 `EPISODE_START` 和一条 `EPISODE_END`。

**流程**：
1. `state = self._begin(episode_id, task)`——重置世界、写 `EPISODE_START`、构造初始 `LoopState`。
2. 用 `try/except Exception` 包裹图的执行：
   ```python
   final = self._graph.invoke(state, {"recursion_limit": task.max_steps * 6 + 20})
   ```
   **`recursion_limit` 怎么算**：`task.max_steps * 6 + 20`。注释解释："每一步走三个节点，留一倍余量"——即每步（look → retrieve_memory → think → press/push_goal/inspect → [remember] → 回到 look）大致对应 LangGraph 计数的若干个节点转移，估算约 3 个节点转移每步，乘以 6 是留了一倍余量（3×2=6），`+20` 是额外的固定缓冲（覆盖 `_begin` 之外图内部的开销及边界情况）。这个上限只是"图执行不要陷入死循环/超长递归"的安全阀，真正的步数上限由 `_observe` 里 `state.step >= state.task.max_steps` 判定并触发 `done`。
3. **异常处理**：若图执行抛出任何 `Exception`：
   - 先 `self._trace.append(*trace_utils.episode_error(episode_id, task.task_id, exc))` 补写一条 `EPISODE_END`（`success="False"`, `steps="-1"`, `reason="error"`, `task_id`, `why=f"{type(exc).__name__}: {exc}"[:300]`）。
   - 注释解释了为什么必须补：**异常逃出去之前必须把 `EPISODE_END` 补上**。不补的话这一局在事件流里永远"没有结束"——离线统计成功率时它既不在成功里也不在失败里，**直接从分母上消失**——而 `MaxRetriesExceeded`（决策模型连着几次吐不出合法动作）恰恰是最该被记成失败的那一类。
   - 记完后**照常向外抛出**（`raise`，不带参数，保留原始异常和堆栈）：这一局确实跑不下去了，吞掉异常只会让调用方拿到一个语义不明的空结果。
4. 若图正常结束：`outcome = LoopState.model_validate(final).outcome`；断言 `outcome is not None`（"the graph must not end without an outcome"——图只有在 `look` 判定 `obs.done` 时才会走向 `END`，而那条路径必然先经过 `_outcome` 写好了 `outcome` 字段）；返回 `outcome`。

---

## 7. 一轮循环产生的事件类型时间线（示例：press 分支）

以"某一步、栈深为 2（任务目标 + 一个子目标）、模型一次决策成功选中 `press`、执行后记忆库检测到语义记忆条目"为例，按因果顺序列出事件序列（`step` 列为该事件所标注的步号，`n` 为本轮循环开始时的 `state.step`）：

| 顺序 | 事件类型（`EventType`） | 产生节点/方法 | Source | step 标注 | 说明 |
|---|---|---|---|---|---|
| 1 | `MODEL_CALL`（感知） | `_look` → `_observe` | `PERCEPTION` | n | 若本帧未命中缓存，记一次感知调用；命中缓存则此项省略（0 条） |
| 2 | （可能）`ERROR` | 同上 | `PERCEPTION` | n | 仅当上条调用解析失败 |
| 3 | `OBSERVE` | `_look` → `_observe` | `PERCEPTION` | n | payload 含 `goals`——**判定弹栈之前**的栈快照 |
| 4 | `MODEL_CALL`（判定）×2 | `_look` → `_observe` → `_judge` → `_judge_all` | `JUDGE` | n | 并发发出，栈深 2 层各判一次；记账按 depth 顺序串行写 |
| 5 | （可能）`ERROR`×若干 | 同上 | `JUDGE` | n | 仅当某层判定调用失败 |
| 6 | `GOAL_POP`（若有目标完成，非本例——假设本例两层均未完成，则本轮无 `GOAL_POP`） | `_judge` | `JUDGE` | n | 本例假设未完成，跳过 |
| 7 | `MEMORY_READ` | `retrieve_memory` | `DECISION` | n | payload 含 `count`/`refs` |
| 8 | `MODEL_CALL`（决策）×N | `think` | `DECISION` | n | N = 本次 `choose()` 尝试次数（含重试） |
| 9 | （可能）`ERROR`×(N-1 或 N) | 同上 | `DECISION` | n | 每次解析失败补一条 |
| 10 | `THINK` | `think` | `DECISION` | n | 选中动作为 `press`，payload 含 `thought`/`action`/`args`/`rationale`/`attempt` |
| 11 | `MODEL_CALL`（感知，执行期间）×若干 | `press` | `PERCEPTION` | n | 执行后重新感知产生的调用，通常较少或为 0 |
| 12 | （可能）`ERROR` | 同上 | `PERCEPTION` | n | 仅当解析失败 |
| 13 | `ACT` | `press` | `WORLD` | n | payload 含 `action`/`args`/`message` |
| 14 | `MEMORY_WRITE` | `remember` | `HARNESS` | n | payload 含 `key`/`content` |
| 15 | `OBJECT_NOTE`×M | `remember` | `HARNESS` | n | M 为 `note_step` 新建/更新的语义记忆条目数（可为 0） |

之后 `step` 自增为 `n+1`，图回到 `look`，下一轮从事件 1 重新开始，此时 `step` 标注变为 `n+1`。

**关键顺序约束（源码注释强调的因果顺序）**：
- `_observe` 内部：感知调用记账 → `OBSERVE` → 判定调用记账 → `GOAL_POP`（若有）。这是"先记产生这一帧观测的那几次感知调用，再记观测本身，最后才是基于它的判定"。
- `retrieve_memory` 先于 `think` 的决策调用：检索发生在决策模型调用之前，事件顺序照实写。
- `press` 内的 `ACT` 与 `remember` 内的 `MEMORY_WRITE` 都标注为同一个 `step`（本轮开始时的 `n`，即 `before.step`）；`step` 的自增放在 `remember` 链路末尾，确保下一轮 `look` 产生的 `OBSERVE` 才是标注为 `n+1` 的第一条事件。若提前在 `press` 里自增，`ACT`/`MEMORY_WRITE` 与下一步的 `OBSERVE` 会标注错乱的步号，读日志者会把当前记忆误读成下一步的。

若本轮 `think` 选中的是 `push_goal` 或 `inspect`，则不会经过 `press`/`remember`，链路在事件 10（`THINK`）之后直接产出对应的 `GOAL_PUSH`（`push_goal` 分支）或 `MODEL_CALL`(感知)+`INSPECT`（`inspect` 分支），随即 `step` 自增，回到 `look`——不产生 `ACT`/`MEMORY_WRITE`/`OBJECT_NOTE`。
