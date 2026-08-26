# Harness 技术规格说明

源文件：`pokemon_agent/harness/harness.py`

本规格基于源文件的实现与模块内嵌的设计说明整理，目标是"仅凭本文档即可复现出与源码一致的图结构与事件流"。

> **不再标注行号。** 上一版每个小节都挂着 `harness.py:295-334` 这样的坐标，
> 一次重构之后全部失效，而失效的坐标比没有坐标更糟——它会把人带到错误的地方。
> 按方法名索引，方法名改了这份文档也就该改了。

---

## 1. 模块定位与设计哲学

### 1.1 为什么叫 Harness——一次改名的历史

以前叫 `harness` 的那个类，实际上是**工具层**（大脑怎么碰环境）；真正在做控制循环的是图的装配代码。旧名字掩盖了这个事实，导致"一步"这个概念**没有唯一的主人**——`world` 在数 step，旧 harness 在猜边界，图在决定什么时候算一轮，三方各自维护一份，最终需要"按步去重来对账"。

改名 + 重构之后只剩两个角色：

- **`LoopState`** 拥有"这一局跑到哪了"。`step` 在这里盖章，别的角色只读不写。
- **`Harness`** 拥有生死判断与记账职责，**自己不持有任何状态字段**（`__init__` 只挂 `game`/`memory`/`brain`/`trace` 四个端口、`run_id`、`episode_state_dir` 和编译好的 `_graph`）。

### 1.2 唯一性规则

1. **`LoopState` 拥有"这一局跑到哪了"**：`step`/`goals`/`succeeded`/`why` 全在 `LoopState` 里流转，不是 `Harness` 的实例字段。
2. **`Harness` 本身无状态**。
3. **只有 Harness 写 trace**。大脑把账（`ModelCall`）连同结果一起交出来，由 Harness 翻译成事件。判定器碰不到自己的账不是特权设计，而是所有大脑调用的共同处境——凡是要花钱调模型的组件，记账权一律收归 Harness。

   **"唯一写"不等于"唯一拼"**：`Harness` 只调 `self._trace.append(*trace_utils.xxx(...))`；把领域对象翻译成 `append()` 的五元组，委托给纯函数模块 `pokemon_agent/trace/utils.py`。调用点（"这一步该不该记、记成哪类事件"）留在 Harness，组装点（"记的话该长什么样"）在 `trace_utils`。

### 1.3 状态为什么全在 LoopState 里——判据是"会不会影响下一个 prompt"

早先按"活多久"分：单步流转的进 `LoopState`，`episode_id`/`task`/`step`/`succeeded` 当实例字段。理由是"图状态会被复制、合并、快照"，但那句话只对**活对象**（world/tools/brain/trace）成立；episode 的身份是**纯数据**，恰恰是 checkpoint 唯一需要的那部分。放在实例字段里，等于把"跑到哪了"存在 checkpointer 看不见的地方。

现行判据统一为**"它会不会影响下一个 prompt"**。据此 `LoopState` 收纳一局的全部可序列化状态，活对象一个都不进来。

### 1.4 光有 LoopState 还复现不了

恢复目标是"恢复 state + 恢复模拟器存档 = 接着往下跑"，还缺一样：

- **记忆库**：进 prompt，但既不在 state 也不在存档里。

**这里原来还有第二个洞：`world._facing`。** 朝向当时是从我们自己的动作历史推的，
不在 pyboy 的 save state 里，而它进 `facts`、进 prompt。现在朝向直接读 RAM
（精灵表 `+9`，见 `ram.read_facing`），存档里有它，洞自然没了——
world 不再持有任何推导出来的状态。

补法留给阶段 2 的 `Checkpoint`：`LoopState` + 记忆库 + 模拟器存档 + manifest。

两个概念要分清：**replay** 是不调模型、从 trace 里取 `raw` 重新解析（只需要 trace）；**resume** 是接着跑（需要完整 checkpoint）。

### 1.5 为什么还是 LangGraph 而不是 while

转移条件是显式的边，将来往中间插节点（状态归并、值回填、成本熔断）不需要改循环体。LangGraph 只承担循环调度与状态传递，记忆和状态表全部自研。

### 1.6 权限：`@initialize` 与横切的装饰器

`run()` 挂着 `agent_permission` 的 `@initialize`：每局开始前重新加载 `config/context.json` 与 `config/permissions.json`。权限检查本身以装饰器形式散在**工具层**（`GameTools`/`MemoryTool` 的每个方法）和**大脑**（`choose`/`judge`/`reflect`）上，不由 Harness 逐个调用——它是横切设施，不是循环的一环。

Harness 这一侧只承担一件事：**权限失败不能让这一局从 trace 里消失**。见 6.3。

### 1.7 还没做的

六件套目前有 trace 和权限确认（后者只到"装饰器 + 控制台审批"这一步）；缺沙箱、成本上限、checkpoint、replay。

---

## 2. `LoopState`

`pydantic.BaseModel`，"一局的**全部**可序列化状态"。

### 2.1 分组

| 分组 | 字段 | 特点 |
|---|---|---|
| 身份 | `episode_id` / `task` / `step` / `goals` / `succeeded` / `why` | 跨步存活，是 checkpoint 要恢复的那部分 |
| 流转 | `observation` / `space` / `memories` / `action` / `press_result` | 单步内，从一个图节点传到下一个 |

### 2.2 完整字段表

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `episode_id` | `str` | 必填 | 这一局的标识，全局唯一。trace 按它分组 |
| `task` | `Task` | 必填 | 目标、判据、步数上限都在里面 |
| `step` | `int` | `0` | 跑到第几步。**全项目只有这一个 step** |
| `goals` | `list[Goal]` | `[]` | 目标栈。**当前目标恒为栈顶 `goals[-1]`**；这一版栈恒为一层，见第 5 节 |
| `succeeded` | `bool` | `False` | 判定器说过达成了没有。一旦为真就不再问——结论不会反悔 |
| `why` | `str` | `""` | 判成功时的依据。成功率是要报的数字，每个 `True` 都得说得出依据 |
| `observation` | `Observation \| None` | `None` | 当前这一步 `look` 拿到的观测 |
| `space` | `ActionSpace \| None` | `None` | 本步可用按键 |
| `memories` | `list[StepMemory]` | `[]` | `retrieve_memory` 查出来、给这一步 `think` 用的情景记忆 |
| `action` | `Action \| None` | `None` | `think` 选出的动作 |
| `press_result` | `Observation \| None` | `None` | `press` 执行后的新观测，交给紧跟着的 `remember` |

### 2.3 这里**没有** `outcome`

`EpisodeOutcome` 不在 `LoopState` 里。它是这一局的最终结论，由 `run()` 在图跑完之后从 `observation` 直接算出来。

放进 state 就得有个节点负责填它，而"下结论"不该是任何一个循环节点的副业——它曾经是 `_look`（一个叫"看一眼"的节点）顺手做的。更硬的理由见 6.4：`EpisodeOutcome` 和 `EPISODE_END` 的 payload 是同一份信息的两个形态，算在两个地方会静默漂移。

顺带，这也消掉了一个形状问题：`space` 和 `outcome` 曾经互斥填充，`LoopState` 里任何时刻都有一个是上一轮的陈值，靠调用图保证下游不读错——不是靠类型。

### 2.4 `press_result` 的生命周期

"专用信使"字段：只在同一轮循环内由 `press` 写入、由紧接着的 `remember` 读取一次，随后被下一轮 `look` 产生的新 `observation` 在语义上覆盖（字段本身不显式清空）。

---

## 3. 图结构

### 3.1 顶层形状

```
look → retrieve_memory → think → press → remember → look
  └─(obs.done)→ summarize → END
（回到 run()）EPISODE_END
```

**一条直线，没有分派。** 以前 `think` 出口按 `Action.intent` 分三岔（press / push_goal / inspect），现在只剩按键一类动作——`Intent` 枚举连同 `Action.intent`、`ActionSpace.intents`、`push_goal` 节点、`GOAL_PUSH` 事件一起删了。拆子目标的机制会在别处重写。

**这里曾经有一条"细看"（inspect）链路**：`WorldPort.inspect()` 单独再问一次视觉模型，
结果落进 `facts["inspected"]`，并由 `trace.inspect()` 记成一条 `INSPECT` 事件。
它整条被删了——它烧的是一次和 `perceive()` 同源的感知调用，看的还是同一帧，
换来的只是"再描述一遍"；而且它自成一步（算进 `max_steps`），
于是模型学会了用"再看一眼"来拖时间，那一步既不推进世界也不写记忆。
真正要补的是感知本身讲得够不够清楚，不是在循环里多开一个只看不动的出口。

`EventType.INSPECT` 这个枚举值**留着**（`trace/store.py` 里也仍有它的显示分支）：
旧 trace 文件里有这类事件，回放不能因为枚举里没有这个值就整条读不出来。
枚举值只增不改，是事件流这种 append-only 数据的基本约束。

### 3.2 节点表

| 节点名 | 方法 | 花不花钱 |
|---|---|---|
| `look` | `_look` | 感知（通常命中缓存）+ 判定各一次调用 |
| `retrieve_memory` | `_retrieve_memory` | 不调模型（检索走本地 embedding/reranker） |
| `think` | `_think` | 决策调用 ×N（N 含重试） |
| `press` | `_press` | 执行后重新感知（通常命中缓存） |
| `remember` | `_remember` | 反思调用 ×1 |
| `summarize` | `_summarize` | 蒸馏调用 ×1 |

没有 `_nodes()` 映射表了——那是给 intent 分派用的，直线图上 `add_node` 逐个写反而更直白。

### 3.3 边

- **入口**：`set_entry_point("look")`
- **`look` 的条件边**（判据见 4.3）：`obs.done` → `"summarize"`；否则 → `"retrieve_memory"`。
  **这是图上唯一的终止分支**：看完才知道这一局还要不要继续。放在动作节点出口的话，"步数用尽"和"目标达成"要在两个地方各判一次。
- `retrieve_memory` → `think` → `press` → `remember` → `look`，全是固定边。
- `summarize` → `END`。

### 3.4 ASCII 图

```
                    ┌──────────────────────────────────┐
                    │                                  │
                    ▼                                  │
                ┌────────┐  obs.done?                  │
   entry ──────▶│  look  │──── True ──▶ ┌───────────┐  │
                └────┬───┘              │ summarize │  │
                     │ False            └─────┬─────┘  │
                     ▼                        ▼        │
            ┌────────────────┐               END       │
            │ retrieve_memory│                         │
            └────────┬───────┘                         │
                     ▼                                 │
                ┌─────────┐                            │
                │  think  │                            │
                └────┬────┘                            │
                     ▼                                 │
                ┌─────────┐                            │
                │  press  │                            │
                └────┬────┘                            │
                     ▼                                 │
               ┌───────────┐                           │
               │ remember  │───────────────────────────┘
               └───────────┘
```

### 3.5 为什么 `retrieve_memory` / `remember` / `summarize` 是独立节点

**图结构本身要能一眼看出三条规则**，不用读代码：

| 规则 | 图上的体现 |
|---|---|
| 每一步先查记忆再决策 | `retrieve_memory` 固定挂在 `look` 与 `think` 之间 |
| 只有推进世界那一步才写记忆 | `remember` 只跟在 `press` 后面 |
| 一局只在结束时蒸馏一次经验 | `summarize` 只在 `look` 的终止分支上 |

`summarize` 独立成节点还有一条单独的理由：**它要调一次模型**。藏在收尾逻辑里的时候，图上看不到"这一局结束时还额外烧了一次调用"，读图的人会以为一局的开销就是 `steps × (感知 + 决策 + 判定)`。**图上看得见的东西才会被算进成本。**

反过来，构造 `EpisodeOutcome` **不是**节点：图上的格子代表"发生了一件事"（调模型、推世界、写库），而它不花钱、不改世界、不写记忆，给它一格会稀释"读图 = 看这一局做了哪些真事"这个读法。

### 3.6 收尾为什么不在图里

`EPISODE_END` 写在 `run()`，不在任何节点里。两条理由：

1. `END` 是 LangGraph 的哨兵，不是节点，挂不上动作。
2. 更要紧的是——正常结束和异常终止**都**得写这条事件。写在 `run()` 里两条路径才共用同一个出口；分散到图内图外各写一次，迟早有一条路径漏掉，而漏掉的那些局会直接从成功率的分母上消失。

---

## 4. 逐节点方法详解

### 4.1 `_begin(episode_id, task) -> LoopState`

**职责**：开一局：写下边界，重置世界，造出初始状态。**这里不观测**——观测是 `look` 的事，而 `look` 是图的入口。记忆**不清空**——跨任务复用经验正是要验证的东西。

**流程（顺序是刻意的）**：

1. **先写 `EPISODE_START`**（`Source.HARNESS`），payload 含 `task_id`/`goal`/`max_steps`/`memory_carried`（当前情景记忆条数，是 A/B 实验的自变量本身）。

   **在做任何事之前就写。** 以前它排在 `reset()`/`save_state()` 之后，注释却声称"episode 的边界应该是这一局在事件流里看到的第一条事件"——那句话只在这两步都成功时才成立。`reset()` 要调模拟器和视觉模型，`save_state()` 挂着唯一那条 `approval_required` 的权限，两者都可能抛；抛在这一行之前的话，`run()` 的兜底只会补一条 `EPISODE_END`，事件流里出现一个没有开头的结尾，比彻底没有记录更难读。

   代价是"这一局可能一步没跑就结束了"，但那本来就是事实，`EPISODE_END` 的 `reason` 会说清楚。

2. `reset = self._game.reset(task)` 真实重置世界（通常含一次真实的开局感知）。
3. 若配置了 `episode_state_dir`，`self._game.save_state(...)` 存一份起点存档。
4. 对 `reset.calls` 逐条当场记账（`Source.PERCEPTION`），**不留到下一次 `_observe()` 才补记**。
5. 构造 `LoopState`，`goals=[Goal(goal=task.goal, criteria=task.success_criteria)]`——栈底是任务目标本身，"它永远在，也永远是成败的唯一依据"。

**trace 事件**：`EPISODE_START` ×1（先）→ `MODEL_CALL`（+ 可能的 `ERROR`）×若干，均 `step=0`。

### 4.2 `_look(state) -> dict`

**职责**："每一步都从这里开始。"调 `_observe(state)` 拿到 `(obs, goals, succeeded, why)`，写回 state。

开局那一帧也走这里（它是图入口），所以"起点存档就已经满足判据"的 episode 会在第 0 步就被判出来，一步都不用走——不这样的话这类局会白跑满步数，而成功率里少掉的正是最容易达成的那些。

**返回值是状态增量，不是"结果"**：LangGraph 的节点约定（CLAUDE.md 第五节）——返回的 dict 只放**这一步改了哪些字段**，由 LangGraph 合并进 `LoopState`，没写进去的字段保持原样。

```python
update = {"observation": obs, "goals": goals, "succeeded": succeeded, "why": why}
if not obs.done:
    update["space"] = self._game.get_action_space()
return update
```

只有"接着跑"那条分支多带一个 `space`（`think` 要用）；终止那条什么都不多给——**这一局的结论由 `run()` 算**。

`space` 直接来自工具层：`intents` 那一层没有了（`ActionSpace` 里连这个字段都删了），Harness 不再覆写它。

**trace 事件**：不直接写，全部委托给 `_observe`（及它调用的 `_judge`）。

### 4.3 `look` 出口的路由

判据是 `"summarize" if state.observation.done else "retrieve_memory"`，写在 `_compile()` 里
`add_conditional_edges` 的内联 lambda 上，是图上唯一的终止分支。**不直接连 `END`**——
终止要先经过蒸馏。不写 trace。

（`harness.py` 里还留着一个同名的 `_look_route` 方法，但它已经不在图上：
条件边挂的是上面那个 lambda。**以方法名索引这份文档时以图的装配为准。**）

### 4.4 `_retrieve_memory(state) -> dict`

**职责**：这一步**全部的记忆读**都在这里发生。图上单独一格，是"查记忆"唯一的入口。

**流程**：

1. `memories = self._memory.query_episode_steps(episode_id)`——**这一局**全部的单步情景记忆，按 `step` 升序，**不做相关性排序、不截断**。
2. `known = self._memory.query_objects(obs)`（语义记忆·object，按坐标筛）；非空则折进 `obs.facts["known_objects"]`。
3. `knowledge_result = self._memory.query_knowledge(query=task.goal, limit=MEMORY_RECALL_LIMIT)`（语义记忆·knowledge，和坐标无关的通用先验，走混合检索）；非空则折进 `obs.facts["knowledge"]`。
4. 若 `obs.place` 非 None，用 `map:.. | scene:.. | overlay:..` 拼出 `scene_key`，`self._memory.query_episode_summaries(scene=scene_key, query=task.goal, limit=EPISODE_MEMORY_RECALL_LIMIT)` 取跨局摘要记忆；非空则折进 `obs.facts["episode_memories"]`。
   - 查询词用 `task.goal` **而不是当前快照**：`EpisodeMemory.render()` 里压根没有位置/地标这些字段，拿快照去比只会一条都选不中。
5. 写一条 `MEMORY_READ`。

**为什么四种读都折进 `obs.facts` 而不是各开一个字段**：对 `think()` 而言它们和 `walk_map`/`landmarks` 一样，都是"当前状态的一部分"，这样不用动 `decide_action.md` 的 `$facts` 渲染逻辑。

**为什么不放在 `_observe()`（`look` 节点）里**：它们是记忆的读，不属于"看一眼"。这不只是分类洁癖——早先塞在 `_observe()` 里时，`knowledge` 会在 `_judge()` 跑之前就出现在 `obs.facts` 里被判定模型看到，白白花 token（判定本不该看这类字段，见 `brain/SPEC.md` 的 `JUDGE_BLIND`）。现在 `_judge()` 在 `_observe()` 内部先跑完，`retrieve_memory` 是后一个节点，判定模型天然看不到。

**常量**：`MEMORY_RECALL_LIMIT = 5`（知识库检索条数）、`EPISODE_MEMORY_RECALL_LIMIT = 3`（跨局摘要条数，比前者小：那是"别的局蒸馏出的经验"，本来就该比"这一局刚发生的事"占更少 prompt 篇幅）。

**trace 事件**：`MEMORY_READ` ×1（`Source.DECISION`）。检索发生在决策调用之前，事件顺序照实写——**因果顺序，不是排版偏好**。

### 4.5 `_think(state) -> dict`

**职责**：调大脑决策，把大脑交回的账翻译成事件。一次 `choose()` 可能因解析失败重试多次，所以这里产出的是一组事件。

三类事件分开写，因为它们回答不同的问题：

| 事件 | 回答 |
|---|---|
| `MODEL_CALL` | 每次尝试花了多少——失败的那几次同样烧了钱 |
| `ERROR` | 每次为什么失败——按 `kind` 聚合就是失败模式分布 |
| `THINK` | 最终选了什么 |

**流程**：`decision = self._brain.choose(goals, observation, space, memories)`（**不重新查记忆**，直接用 `state.memories`）→ 断言 `decision.calls` 非空 → 逐条记账 → 若 `decision.action is None` 写一条 `ERROR`（`kind="MaxRetriesExceeded"`）并 `raise MaxRetriesExceeded` → 否则写 `THINK`。

**抛异常的是这里，不是大脑**：大脑只汇报"一次都没解析出合法动作"，而"这一局是否因此终止"是循环的判断。

### 4.6 `_press(state) -> dict`

**职责**：按键，推进世界。**只管执行和账，不写记忆**；**`step` 也不在这里加**——`press → remember` 是一个整体，加一次的地方在链路末尾。

**流程**：`result = self._game.execute(action)` → 断言 `result.observation` 非空 → 对 `result.calls` 逐条记账（`Source.PERCEPTION`）→ 写 `ACT`（`Source.WORLD`，step 用 `before.step`）→ 返回 `{"press_result": result.observation}`。

**一步交出去的是一整条动作链。** `Action.sequence`（`list[ActionSegment]`，每段是
"按哪个键 × 连按几次"）由**一次** `execute()` 整条交给 world，world 只在**链尾**感知一次。
所以一步之内的感知事件数是 **1**（还常常因为帧缓存变成 0），不再随按键次数增长——
走 5 格从 5 次视觉调用变成 1 次，成本和延迟一起砍到五分之一。
代价是链的中间状态 agent 看不见：撞墙了也会把剩下几次按完。这是时序抽象的经典取舍，
`MAX_TIMES` 是给它的闸。

**`ACT` 记的是结构化的链本身**（`trace_utils.action_chain()`，`think` 和 `act` 共用它，
所以"想按的"和"按下去的"能逐字段比对）：`sequence`(json) / `segment_count` /
`press_count`，外加给人读的一行 `action`（`up×4 -> down×2`）。

**这里曾经还记一个 `message`：** `ToolResult.message`，world 返回的一句"结果描述"。
它的字段说明写着"给 LLM 读的"，而全仓库唯一的消费方就是这条 `ACT` 事件；内容又只是
`observation.status`，紧接着还会作为下一条 `OBSERVE` 的 `status` 再出现一遍，
观测台上纯属复读。字段和 `trace_utils.act()` 的那个参数一起删了——现在签名是
`act(episode_id, step, action)`。**按完之后世界变成什么样，答案是下一条完整的 `OBSERVE`，不是一句转述。**

新观测**没盖过章**（`step` 恒 0），但 `remember` 只取它的 `Snapshot`——里面全是 facts，和步号无关。

### 4.7 `_remember(state) -> dict`

**职责**：把 `press` 刚推进的这一步写进记忆。

**流程**：

1. `entry = self._brain.reflect(before, action, after).model_copy(update={"episode_id": ep})`——`episode_id` 在这里盖章，因为大脑不知道自己在哪一局。
2. `self._memory.store_episode_step(entry)` + 写 `MEMORY_WRITE`。
3. `for note in self._memory.store_objects_interactions(before, action, after)` 逐条写 `OBJECT_NOTE`（可能一条都没有，见下）。
4. 返回 `{"step": state.step + 1}`。

**两类记忆分开写**：情景记忆记"我在那种画面里选了什么"（作用域是一次经过）；`OBJECT_NOTE` 记"地图39 x=2 y=3 那个人会说什么"（作用域是那一格，域内恒真、域会再现）。后者不需要模型判断——面朝哪一格由 `place + facing` 算出，两个输入都确定。

**动作链让这一类记忆多了一条"宁可不记"的规则**（在 `MemoryTool` 那侧，Harness 只是照单转记）：
多段链、以及单段但连按（`times != 1`）的移动，**一律不记**。这份档案的键是
「在哪一格按了哪个键」，而一条链的 `before`/`after` 是**整条链的两头**——中间路过了哪些格子、
哪一次按键才是撞在门上的那一次，这里都看不到。把 `up×4 -> down×2` 记成"在起点按了一次 up"，
写进去的是一条**假的尝试记录**。少记一条只是慢一点；记错一条会让它以后永远不再试那个正确的碰法。

所以链一长，这一步的 `OBJECT_NOTE` 数就是 0——**这不是漏记，是这一步确实没有可信的证据。**

**顺序不能换**：`ACT`（在 `press`）和 `MEMORY_WRITE`（这里）都属于第 n 步，`step + 1` 放在链路末尾，下一轮 `look` 写的 `OBSERVE` 才落在第 n+1 步。提前加一的话事件流的步号会往回跳。

### 4.8 `_observe(state) -> tuple[Observation, list[Goal], bool, str]`

**职责**：全项目**唯一**产出 `Observation` 的地方；读一帧，盖上步号与终止判断，判一次成败，记进 trace。

只有 `_look` 调它，所以"一步恰好一次"——这正是这一版不需要 `_traced_step`/`_judged_step` 那两个去重字段的原因：一步一次是**调用图的形状本身**保证的。

**终止的三个来源，这里全判了**：

- **步数用尽**——只有这一层知道走了几步。
- **世界不可用**（窗口被关）——world 自己置 `done`，这里保留。
- **目标达成**——问大脑，见 `_judge`。

**流程**：`perceived = self._game.perceive()` → 盖 `step` 和 `done` → 对 `perceived.calls` 逐条记账（`ok != "True"` 时标 `PerceptionParseFailure`）→ 写 `OBSERVE` → `return self._judge(state, obs)`。

`OBSERVE` 的 payload 含 `frame_sha`/`status`/`scene`/`overlay`/`facts`(json)/`goals`。**`goals` 记的是判定弹栈之前的栈**——`OBSERVE` 必须先于本步的判定事件（因果顺序），判完之后的栈会在随后的 `GOAL_POP` 里体现。

字段名是 `status` 不是 `summary`：`Observation.summary` 改叫 `Observation.status` 了——
那一行是 scene + overlay 机械拼出来的**状态行**（`你在野外。对话框：「…」`），
不是画面描述。画面描述是视觉模型写的 `facts["overview"]`，叫 summary 会让人以为
"读这一个字段就等于看过这一帧"，而实质内容一直在 `facts` 里。

**`known_objects`/`knowledge` 不在这里拼**：见 4.4。

**事件顺序是因果顺序**：先记产生这一帧观测的那几次感知调用，再记观测本身，最后才是基于它的判定。反过来记的话，拿事件流做 replay 的人会先看到结果、再看到产生它的原因。控制台上排版不好看是**显示层的问题**，在显示层解决——不能为了排版去改事件流。

### 4.9 `_judge(state, obs) -> tuple[...]`

**职责**：**判栈顶那一条。完成就出栈。**

**算法**：

1. **早退分支**：若 `state.succeeded` 已为真，直接返回 `(obs.model_copy(done=True, success=True), state.goals, True, state.why)`。当前图内走不到（判成成功的那一步同时置了 `obs.done`），但 resume 会：从一个 `succeeded=True` 的 checkpoint 恢复时，不打标记的话 `look` 的条件边不去 summarize、转而进 `think`，而那时 `goals` 已是空的，`brain.choose` 的 `assert goals` 会当场崩掉。
2. `history = self._memory.query_recent_steps(episode_id, JUDGE_HISTORY)`。
3. `verdict = self._brain.judge(goals[-1], obs, history)`。
4. 写判定的账（`Source.JUDGE`），`depth = len(goals) - 1` 塞进 payload。
5. 未完成 → `return obs, goals, False, ""`。
6. 完成 → 写 `GOAL_POP`（`reason="done"`）→ `remaining = goals[:-1]` → 若 `remaining` 为空（栈空 = 任务完成）返回 `(obs.model_copy(done=True, success=True), remaining, True, verdict.why)`；否则返回 `(obs, remaining, False, "")`。

**两个补充规则**：`obs.done` 不是跳过判定的理由（那里的 `done` 是"步数用尽"，而任务完全可能恰好在最后一步达成）；判过成功之后不再问（结论不会反悔）。

**判定的账单单独记**（`Source.JUDGE`）：它和决策各自烧 token，混在一起就说不清"成功率这个数字本身花了多少钱"，也算不出判定器自己的失效率。判定失败会顺带补一条 `ERROR`——"判了没完成"和"根本没判出来"必须分得开，否则判定器坏掉时表现就是成功率悄悄变成 0，而没人知道为什么。

### 4.10 `_summarize(state) -> dict`

**职责**：图上的最后一格，把这一局蒸馏成一条跨局摘要记忆。

`success`/`steps` **直接从 `state.observation` 读**，不经过 `EpisodeOutcome`。

**为什么是这里、而不是每一步**：单步情景记忆和语义记忆（object）才是每步在 `_remember()` 里落盘的那两类；跨局摘要记忆的**检索单元是一整局**，自然也只在一整局跑完之后蒸馏一次。

**只吞 `ValueError` 这一种失败**：蒸馏解析不出合法结构时 `EpisodeMemoryGenerator.generate_summary` 抛 `ValueError`，且已在内部留了一条 `ERROR` trace 事件。**单据齐全才吞**——那条 ERROR 是它出现在失败模式统计里的凭证，没有凭证的静默吞掉就是在丢数据。吞掉是因为蒸馏失败不该拖累这一局本该正常记的 `EPISODE_END`：这一局确实跑完了，只是没能力提炼经验，这是两件事。别的异常照常往上抛。

**`EPISODE_END` 不在这里写**——它在 `run()`。

---

## 5. 目标栈

`goals` 这个栈的形状留着，但**这一版它恒为一层**：栈底是任务目标，而压栈的唯一途径 `push_goal` 已经删了。**当前目标永远是栈顶**（`goals[-1]`），判定只判它，完成就出栈；栈空 = 任务完成，只有这一条路径写 `success`。

`if not remaining` 在只有一层时永远成立。留着它不是为了当下分支，而是把"只有任务目标本身完成才算成功"写成代码——子目标回来之后，agent 自己压的那些完成了只该弹栈，不该给自己发奖状。

### 5.1 这里曾经有一套多层并发判定

`_judge_all` + `reason="superseded"`：每层各判一次（`ThreadPoolExecutor` 并发发出），最深的那条"已完成"连同它上面的全部出栈。前提是**栈会长起来**，现在不会。

对一层的栈来说，"每层各判一次"和"判栈顶"是同一件事，只是前者还额外背着一个线程池、一段"模型调用并发但写 trace 不并发"的注意事项（`event_id` 必须单调，那是 SSE 断线补发的唯一依据），以及一个恒等于 0 的 `depth`。

当时那份权衡记在这里，**不留在代码里占位**——占位的抽象会把下一版往旧形状上带：

- **并发而不是把整栈塞进一次调用**：合成一次会丢掉**判定之间的隔离**（模型同时看到任务目标和子目标就会互相推理，"子目标完成了，那任务应该也快了"）和**可标定性**（单目标判定是干净的二分类 `(目标, 判据, 帧) → 0/1`，可以人工标注算准确率；合成一次后输出是长度可变的向量，而且同一份 prompt 在栈深 1 和栈深 4 下不是同一个东西，误差不再独立）。合并省的是 token，不是时间——token 那头由 prompt 的字段顺序解决（固定说明和画面在前、目标在最后，同一步内几次调用共享一大段前缀）。
- **不再有提前退出**：顺序版判到第一条完成的就停能省几次调用，并发版全判。用 token 换墙钟。

拆解机制在别处重写时，多层判定要不要回来、以什么形状回来，是**那时**的决定。

`goal_pop` 的 `reason` 字段留着（现在只有 `done` 一个取值）：拆解回来时"完成"和"白拆"仍然必须分得开，而那是判断目标栈到底帮没帮上忙的那个数。

### 5.2 常量

- `JUDGE_HISTORY = 3` —— 判定器能看到本局最近几步。不是 0：证据可能在三步以前那一帧的对话框里。也不是"全部"：判定是每步一次，条数一多成本就跟着步数增长。历史里**不含 `rationale`**（`StepMemory.render(reason=False)`）——发生过的事给判定器看，决策者对那件事的主张不给。

---

## 6. `run()` 整体流程

`run(self, episode_id: str, task: Task) -> EpisodeOutcome`，`Harness` **对外唯一的入口**，挂着 `@initialize`（每局重载权限配置）。

**前置条件**：`episode_id` 非空；`task.max_steps > 0`（均用 `assert` 表达）。

**后置条件**：trace 里恰好多一条 `EPISODE_START` 和一条 `EPISODE_END`。

### 6.1 正常路径

```python
try:
    state = self._begin(episode_id, task)
    final = self._graph.invoke(state, {"recursion_limit": task.max_steps * 6 + 20})
except Exception as exc:
    self._trace.append(*trace_utils.episode_error(episode_id, task.task_id, exc))
    raise

final_state = LoopState.model_validate(final)
obs = final_state.observation
assert obs is not None and obs.done, "the graph must not end before the episode does"

reason = ("success" if obs.success
          else "max_steps_exceeded" if obs.step >= task.max_steps
          else "world_ended")
outcome = EpisodeOutcome(episode_id=episode_id, task_id=task.task_id,
                         success=obs.success, steps=obs.step, reason=reason)
self._trace.append(*trace_utils.episode_end(episode_id, outcome, final_state.why))
return outcome
```

**`recursion_limit` 怎么算**：一步走五个节点（look / retrieve_memory / think / press / remember），外加收尾的 `summarize`。`× 6` 留了一倍余量——递归上限撞上去的症状是一局无声截断，宁可给宽。这只是安全阀，真正的步数上限由 `_observe` 里 `state.step >= task.max_steps` 判定并触发 `done`。

### 6.2 `_begin()` 为什么在 `try` 里面

它调 `save_state()`，而 `execute:game:save_state` 是配置里唯一 `approval_required` 的权限。人类拒批或审批超时抛出来的异常要是从这里逃走，这一局**连 `EPISODE_END` 都没有**——正是 6.3 要防的"从分母上消失"。

### 6.3 异常路径：为什么必须补 `EPISODE_END`

不补的话这一局在事件流里永远"没有结束"：离线统计成功率时它既不在成功里也不在失败里，**直接从分母上消失**——而 `MaxRetriesExceeded` 恰恰是最该被记成失败的那一类。

记完照常 `raise`（不带参数，保留原始异常和堆栈）：这一局确实跑不下去了，吞掉只会让调用方拿到一个语义不明的空结果。

**权限失败不单开一个 `except` 分支。** 曾经有一个（catch `PermissionDenied` / `ApprovalExpired` / `ApprovalRejected`），函数体和兜底逐字相同——删掉它程序行为一个字节不变，它只是让人误以为权限失败已经被单独处理过了，于是这件事不会再有人回来做。将来真要按权限名聚合（"哪一项权限最常拦住 agent"），改的地方是 `trace_utils.episode_error()` 内部：那是"把异常翻译成事件"的纯函数的职责，不是控制流的。

> 补充：`agent_permission` 的四个异常类**各自直接继承 `Exception`，没有共同基类**，所以任何"列举权限异常"的写法都会在库新增异常类型时静默漏掉。这也是不列举、只用兜底的实际理由之一。

### 6.4 `outcome` 为什么在这里算

`EpisodeOutcome` 和 `EPISODE_END` 的 payload 是**同一份信息的两个形态**（`success`/`steps`/`reason` 逐字段对应）。算在两个地方，迟早不一致——而不一致时**没有任何东西会报错**：返回值说成功、事件流说失败，离线统计和调用方各信一半，要等到对账才发现。写在一起、从同一个 `obs` 派生之后，不一致在结构上就不可能。

不包成方法是因为它只有这一个调用方，而且是三行纯翻译；包起来只会让"这个数是怎么来的"多隔一跳。

出口断言是 `obs is not None and obs.done`（"图不该在这一局跑完之前结束"），不是"某个字段被填了"——后者才是真正要保的那条。

---

## 7. 模型调用记账机制

账跟着 `PerceptionResult`/`ToolResult` 的返回值走，**不再靠 `drain_calls()`**：

| 来源 | 在哪记 | Source |
|---|---|---|
| `reset()` | `_begin` | `PERCEPTION` |
| `perceive()` | `_observe` | `PERCEPTION` |
| `execute()` | `_press` | `PERCEPTION` |
| `choose()` | `_think` | `DECISION` |
| `judge()` | `_judge` | `JUDGE` |
| `reflect()` | 由 `MemoryTool` 内部产出，不经 Harness 记账 | — |
| 蒸馏 | 由 `EpisodeMemoryGenerator` 内部产出 | — |

旧机制的问题：`drain_calls()` 是"下次谁来取谁就顺手把上一步的账也记了"的隐式时机，账目会跨步错位。新机制要求每个产生调用的接口把 `calls` 随返回值交出来，调用方在**当场**完成记账。

`perceive()` 按帧缓存，所以 `_press` 刚感知过同一帧时，`_observe` 里的 `perceived.calls` 通常是空列表——不产生 `MODEL_CALL`，因为确实没有调用发生。

`execute()` 那一行的账**至多一条**：整条动作链交出去，world 只在链尾感知一次（见 4.6）。
"一步烧几次感知"因此和按键次数脱钩了——按成本读事件流时，`press` 那一格的
`MODEL_CALL` 数不再是"这一步按了几下"的代理指标。

**`trace_utils.model_call()` 是纯函数**：输入一个 `ModelCall`，输出 `list[AppendArgs]`（长度 1 或 2——失败时多一条 `ERROR`），调用方自己逐条 `append`。它不认识 `TracePort`、不做 I/O，可以脱离 Harness 单测。账单和失败模式是两件事：前者回答"花了多少钱"，后者回答"为什么没拿到东西"；混进一条里，按失败类型聚合时就得去解析 payload 里的字符串。

---

## 8. 一轮循环的事件时间线

以"某一步、模型一次决策成功、执行后记忆库检测到语义记忆条目"为例（`n` 为本轮开始时的 `state.step`）：

| 顺序 | 事件 | 节点 | Source | step |
|---|---|---|---|---|
| 1 | `MODEL_CALL`（感知） | `look` → `_observe` | `PERCEPTION` | n |
| 2 | （可能）`ERROR` | 同上 | `PERCEPTION` | n |
| 3 | `OBSERVE` | `look` → `_observe` | `PERCEPTION` | n |
| 4 | `MODEL_CALL`（判定）×1 | `look` → `_judge` | `JUDGE` | n |
| 5 | （可能）`ERROR` | 同上 | `JUDGE` | n |
| 6 | `GOAL_POP`（仅目标完成时） | `look` → `_judge` | `JUDGE` | n |
| 7 | `MEMORY_READ` | `retrieve_memory` | `DECISION` | n |
| 8 | `MODEL_CALL`（决策）×N | `think` | `DECISION` | n |
| 9 | （可能）`ERROR`×失败次数 | 同上 | `DECISION` | n |
| 10 | `THINK` | `think` | `DECISION` | n |
| 11 | `MODEL_CALL`（感知，链尾一次）×0 或 1 | `press` | `PERCEPTION` | n |
| 12 | `ACT` | `press` | `WORLD` | n |
| 13 | `MEMORY_WRITE` | `remember` | `HARNESS` | n |
| 14 | `OBJECT_NOTE`×M（多段链或连按时 M 恒为 0，见 4.7） | `remember` | `HARNESS` | n |

之后 `step` 自增为 `n+1`，回到 `look`。

**终止那一轮**：事件 1–6 之后不进 `retrieve_memory`，改走 `summarize` —— `MODEL_CALL`（蒸馏）+ `EPISODE_MEMORY_WRITE`（蒸馏失败时是 `ERROR`），然后图结束，`run()` 写下最后一条 `EPISODE_END`。

**关键顺序约束**：

- `_observe` 内部：感知调用记账 → `OBSERVE` → 判定调用记账 → `GOAL_POP`（若有）。
- `retrieve_memory` 先于 `think` 的决策调用。
- `ACT`（`press`）与 `MEMORY_WRITE`（`remember`）标注同一个 `step`（`before.step`）；`step` 自增在 `remember` 末尾。
