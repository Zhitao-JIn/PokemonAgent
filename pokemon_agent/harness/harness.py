"""Harness —— **控制一局怎么跑**。它就是以前那张图。

改名的理由：以前叫 harness 的那个类其实是工具层（大脑怎么碰环境），
而真正在控制循环的是 `graph/build.py`。名字盖住了这个事实，
于是"一步"这个概念没有主人——world 在数 step，harness 在猜边界，
图在决定什么时候算一轮，三家各有一份，才需要按步去重来对账。

现在只有一个主人：

    LoopState 拥有"这一局跑到哪了"。step 在这里盖章，别人只读。
    Harness   拥有生死判断与记账。**它自己没有任何字段**，是无状态的。

**Harness 是唯一调 `trace.append()` 的人**，但组装 payload 不是它的活——
"发生了一次 observe 该记哪些字段"是 `trace/utils.py` 里一堆纯函数的事，
这里只管"这一步该不该记、记成哪个 `EventType`"，然后把纯函数吐出来的
`(episode_id, step, type, source, payload)` 原样转给 `trace.append(*...)`。
大脑把账（`ModelCall`）连同结果一起交出来，由这里翻译成事件；
判定器碰不到自己的账不是特权设计，而是所有大脑调用的共同处境。

## 一轮循环长什么样

    look             obs = self._observe(state)    -> MODEL_CALL(感知，通常 0 条，账已在上一步记过) + OBSERVE
                                                      + MODEL_CALL(判定)×栈深 + GOAL_POP×弹了几层
                     space = self._space(goals)
    retrieve_memory  memories = memory.query_episodic(...)
                     obs 折进 known_objects/knowledge（语义记忆的读）  -> MEMORY_READ
    think            d = brain.choose(goals, obs, space, memories)
                                                   -> MODEL_CALL(决策)×N + ERROR×失败次数 + THINK
    ┌ press          tools.execute                 -> MODEL_CALL(感知，通常 0 条) + ACT
    │ └ remember     reflect → memory.write_episodic → memory.note_step
    │                                               -> MEMORY_WRITE + OBJECT_NOTE×N
    ├ push_goal      压一个子目标                    -> GOAL_PUSH
    └ inspect        对同一帧再问一个具体问题          -> MODEL_CALL(感知) + INSPECT
                                                      三条链路都 step += 1，然后回到 look

    `retrieve_memory`/`remember` 是**显式的图节点**，不是藏在 `think`/`press`
    内部的几行代码——"每一步先查记忆再决策""只有真正推进世界那一步才写记忆"
    这两条规则因此是图结构本身，一眼能看见（见 `_compile` 的完整说明）。

**只有 `press` 推进世界。** 另外两类只改变大脑自己的处境，但**同样算一步**——
它们烧的决策调用是一样的，不算的话 `max_steps` 就管不住"一直拆、从不走"这种局。

**观测只在 `look` 里产生，一步一次。** `_observe()` 是全项目唯一给
`step` / `done` / `success` 赋值的地方，而它只有 `_look` 一个调用方。
所以"一步一次观测"不需要任何去重来保证——它是调用图的形状本身。

`press` 里的顺序不能换：`ACT` 和 `MEMORY_WRITE` 都属于第 n 步，
`step + 1` 在最后才发生，下一轮 `look` 记的 `OBSERVE` 才是第 n+1 步。

## 目标栈

`goals[0]` 恒为任务目标，上面是 agent 自己拆的子目标（`push_goal`）。

**每层各判一次（并发发出），最深的那条"已完成"连同它上面的全部出栈。**
一条规则，没有特例：

- 栈底那条必然每步都判（它是其中一层）——任务可能顺手就完成了。
- 中间层完成时，上面那些**当初就是为它拆的**，一起作废（`reason=superseded`），
  不再花步数去做已经没有意义的事。
- 只有栈底那条完成才写 `success`（`if depth == 0`）。子目标是 agent 自己定的，
  能写 success 的话它可以压一个"我已经到家了"让判定器给自己发奖状。

出栈理由分 `done` 和 `superseded` 两种：不分的话算不出**拆出来的子目标有多少是白拆的**，
而那是判断目标栈到底帮没帮上忙的那个数。

判定**并发发出**（`_judge_all`），所以一步的判定延迟是 `max` 而不是 `sum`，
和"把整栈塞进一次调用"一样快，但每条目标仍然各判各的——隔离和可标定性都不丢。
写 trace 不并发：`event_id` 必须单调，那是 SSE 断线补发的唯一依据。

## 状态为什么全在 LoopState 里

判据是**"它会不会影响下一个 prompt"**，不是"它活多久"。

早先我按"活多久"分：单步流转的进 `LoopState`，`episode_id` / `task` / `step` /
`succeeded` 当成实例字段。理由是"图状态会被复制、合并、快照"——那句话只对活对象
（world / tools / brain / trace）成立，它们确实序列化不了。但 episode 的身份是
**纯数据**，而且恰恰是 checkpoint 唯一需要的那部分。放在实例字段里，
等于把"跑到哪了"存在了一个 checkpointer 看不见的地方：
接上 LangGraph 的 checkpointer 也恢复不出第几步、在跑哪个任务。

## 光有 LoopState 还复现不了，这一点要写明

目标是「恢复 state + 恢复模拟器存档 = 接着往下跑」。按上面那条判据数，还差两样：

- **记忆库**（`GameTools._memories`）。它进 prompt，但既不在 state 也不在存档里。
  恢复出来记忆是空的，下一个 prompt 就不一样。
- **`world._facing`**。朝向是从**我们自己的动作历史**推的，不是从 RAM 读的，
  所以 pyboy 的 save state 里没有它——而它进 `facts`、进 prompt。这个洞更隐蔽。

补法是阶段 2 的 `Checkpoint`：`LoopState` + 记忆库 + 模拟器存档 + world 的推导状态
+ manifest（模型型号与 prompt sha——prompt 改了，同一个 state 也复现不出来）。

顺带分清两件事：**replay** 是不调模型、从 trace 里按顺序取 `raw` 重新解析
（用途：改了解析器之后离线重算，不花钱），只需要 trace；
**resume** 才是接着跑，那才需要完整 checkpoint。

## 为什么还是 LangGraph 而不是 while

三段之间的转移条件是显式的边，将来往中间插节点（状态归并、值回填、
权限确认、成本熔断）不需要改循环体。LangGraph 只承担循环调度与状态传递，
记忆和状态表全部是自己实现的。

## 还没做的

**六件套只有 trace 一件**：缺权限确认、沙箱、成本上限、checkpoint、replay。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.interfaces.brain import BrainPort
from pokemon_agent.interfaces.tools import GameToolPort, MemoryToolPort
from pokemon_agent.interfaces.trace import TracePort
from pokemon_agent.schemas.action import Action, ActionSpace, Goal, Intent
from pokemon_agent.schemas.memory_episodic import MemoryEntry, Snapshot
from pokemon_agent.schemas.observation import Observation
from pokemon_agent.schemas.task import Task
from pokemon_agent.schemas.trace import EpisodeOutcome, ModelCall, Source, Verdict
from pokemon_agent.trace import utils as trace_utils

MEMORY_RECALL_LIMIT = 5
"""每次决策检索几条情景记忆。原来是 `Brain` 构造时的 `memory_limit` 参数——
大脑不再持有检索通道之后，"查几条"变成了循环控制的事，搬到这里来。
"""

JUDGE_HISTORY = 3
"""判定器能看到本局最近几步。

不是 0：证据可能在三步以前那一帧的对话框里，而**一条第 10 步才压进来的子目标，
前 9 步根本没人问过它**——那几帧的证据就这么丢了。原来那版靠"每步都问一次"兜底，
兜不住这个洞。

也不是"全部"：判定是每步 × 每层各一次，历史进的是**共享前缀**，
条数一多，一局的判定成本就跟着步数平方增长。三条够覆盖"刚刚发生了什么"。

历史里**不含 `rationale`**（`MemoryEntry.render(reason=False)`）——
发生过的事给判定器看，决策者对那件事的主张不给。
"""

MAX_GOAL_DEPTH = 4
"""目标栈最多几层（含栈底的任务目标）。

有上限不是怕内存，是怕**无限拆解**：拆一层不推进世界，模型在"还没想清楚"的时候
会一直拆下去。到顶之后 `push_goal` 从 `intents` 里掉出去，它就只能去走或者去看。

选 4 不是算出来的，是个起手值。真实分布要看 trace 里 `goal_push` 的深度直方图——
如果绝大多数局只用到 2 层，这个数就该调小；如果频繁顶到 4，说明任务粒度本来就太粗。
"""


class LoopState(BaseModel):
    """一局的**全部**可序列化状态。

    分两组，但两组都在这里——分组只是为了读的人知道哪些跨步、哪些不跨：

        身份    episode_id / task / step / succeeded / why   跨步，checkpoint 要的就是它
        流转    observation / space / action / outcome        单步内，从一个节点传到下一个

    **活对象一个都不进来**（world / tools / brain / trace）：它们序列化不了，
    进来就把整个状态变成不可存的。它们是 Harness 的构造参数，由装配处注入。
    """

    episode_id: str = Field(description="这一局的标识，全局唯一。trace 按它分组")
    task: Task = Field(description="在跑哪个任务。目标、判据、步数上限都在里面")
    step: int = Field(
        default=0,
        description="跑到第几步。**全项目只有这一个 step**。"
        "拆子目标和细看**也算一步**——它们同样烧一次决策调用，"
        "混进同一个数里意味着 max_steps 是一道『总共允许它折腾多少轮』的闸",
    )
    goals: list[Goal] = Field(
        default_factory=list,
        description="目标栈。**`goals[0]` 恒为任务目标，只有它决定 episode 成败**；"
        "上面几层是 agent 自己拆的子目标，完成只弹栈，不写 success",
    )
    succeeded: bool = Field(
        default=False,
        description="判定器说过达成了没有。**一旦为真就不再问**——"
        "结论不会反悔，'已经和母亲说过话了'不会因为多走一步就变回没说过",
    )
    why: str = Field(
        default="", description="判成功时的依据。成功率是要报的数字，每个 True 都得说得出依据"
    )

    observation: Observation | None = None
    space: ActionSpace | None = None
    memories: list[MemoryEntry] = Field(
        default_factory=list,
        description="`retrieve_memory` 查出来的、给这一步 `think` 用的情景记忆。"
        "**图上单独一格**——查什么、查几条是循环控制的决策，不该藏在 `think` 内部",
    )
    action: Action | None = None
    press_result: Observation | None = None
    """`press` 执行动作之后的新观测，交给紧跟着的 `remember` 去写记忆。

    只在 `press → remember` 这一段之间有意义，`push_goal`/`inspect` 不产生它，
    `remember` 结束后被下一轮 `look` 写的新 `observation` 盖过去，不跨步存活。
    """
    outcome: EpisodeOutcome | None = None


class Harness:
    """一局的控制器。**它自己没有状态**——状态全在 `LoopState` 里流。"""

    def __init__(
        self, game: GameToolPort, memory: MemoryToolPort,
        brain: BrainPort, trace: TracePort,
    ) -> None:
        self._game = game
        self._memory = memory
        """情景记忆 + 语义记忆（object）都走这一个端口。**和 `game` 是两个不相关的
        对象**——`GameToolPort` 只碰 world，`MemoryToolPort` 只碰记忆，
        见 `interfaces/tools.py` 的模块说明。
        """
        self._brain = brain
        self._trace = trace
        """裸的 `TracePort`。`Harness` 自己调 `append()`，但从不自己拼
        `dict[str, str]`——payload 全部由 `trace_utils` 里的纯函数组装好，
        这里只负责在正确的时机把它们的输出转给 `self._trace.append(*...)`。
        """
        self._graph = self._compile()

    # ---- 对外只有这一个入口 ----

    def run(self, episode_id: str, task: Task) -> EpisodeOutcome:
        """跑完一局，返回结果。

        前置条件：episode_id 非空、task.max_steps > 0。
        后置条件：trace 里恰好多一条 EPISODE_START 和一条 EPISODE_END。
        """
        assert episode_id, "run() got an empty episode_id"
        assert task.max_steps > 0, f"max_steps must be > 0, got {task.max_steps}"

        state = self._begin(episode_id, task)
        try:
            # 每一步走三个节点，留一倍余量。
            final = self._graph.invoke(state, {"recursion_limit": task.max_steps * 6 + 20})
        except Exception as exc:
            # **异常逃出去之前必须把 EPISODE_END 补上。** 不补的话这一局在事件流里
            # 永远"没有结束"：离线统计成功率时它既不在成功里也不在失败里，
            # **直接从分母上消失**——而 `MaxRetriesExceeded`（决策模型连着几次
            # 吐不出合法动作）恰恰是最该被记成失败的那一类。
            #
            # 记完照常往外抛：这一局确实跑不下去了，吞掉只会让调用方拿到一个
            # 语义不明的空结果。
            self._trace.append(*trace_utils.episode_error(episode_id, task.task_id, exc))
            raise

        outcome = LoopState.model_validate(final).outcome
        assert outcome is not None, "the graph must not end without an outcome"
        return outcome

    def _begin(self, episode_id: str, task: Task) -> LoopState:
        """开一局：重置世界，写下边界，造出初始状态。

        **这里不观测**——观测是 `look` 的事，而 `look` 是图的入口。
        记忆**不清空**——跨任务复用经验正是要验证的东西。
        """
        reset = self._game.reset(task)

        # `reset()` 里那次真实感知产生的调用记录，当场记账——**不留到下一次
        # `_observe()` 才补记**。第一次 `look` 会命中这里刚建好的缓存，
        # 这个 episode 只会有这一次真正的开局感知。
        for call in reset.calls:
            failed = call.get("ok") != "True"
            for args in trace_utils.model_call(
                episode_id, 0, Source.PERCEPTION,
                ModelCall(
                    payload=call,
                    error_kind="PerceptionParseFailure" if failed else "",
                    error=call.get("raw", "")[:200] if failed else "",
                ),
            ):
                self._trace.append(*args)

        self._trace.append(
            *trace_utils.episode_start(episode_id, task, self._memory.episodic_size)
        )
        # 栈底是任务目标本身。**它永远在，也永远是成败的唯一依据。**
        return LoopState(
            episode_id=episode_id, task=task,
            goals=[Goal(goal=task.goal, criteria=task.success_criteria)],
        )

    # ---- 图 ----

    def _compile(self) -> CompiledStateGraph:
        """look → retrieve_memory → think → (press → remember | push_goal | inspect) → look

        **分派放在图的边上，不是某个节点里的 if。** 这样"agent 能做哪几类事"
        在图上一眼看得见，加一类 = 加一个枚举值 + 一个节点 + 一条边，
        `_think` 和 prompt 的形状都不用动。

        `retrieve_memory` / `remember` 也是**显式的图节点**，不是藏在 `think`/`press`
        内部的几行代码。以前查记忆是 `_think()` 里的第一步、写记忆是 `_press()`
        里的最后几步——功能上没问题，但图上只看得到 `think`/`press` 两个方框，
        看不出"每一步都先查记忆再决策""只有真正推进世界那一步才写记忆"这两条规则。
        拆成独立节点之后这两条规则**是图结构本身**，不用看代码也看得出来；
        以后想换检索/写入策略，改的是这一个节点，`think`/`press`/prompt 都不用动。

        `remember` 只跟在 `press` 后面——`push_goal`/`inspect` 不推进世界，
        写进去就是一堆"结果：什么都没发生"，会把检索结果稀释掉（原因见 `_remember`）。
        """
        graph = StateGraph(LoopState)
        graph.add_node("look", self._look)
        graph.add_node("retrieve_memory", self._retrieve_memory)
        graph.add_node("think", self._think)
        graph.add_node("remember", self._remember)
        for intent, node in self._nodes().items():
            graph.add_node(intent.value, node)

        graph.set_entry_point("look")
        # **唯一的终止分支在 look 出口**：看完才知道这一局还要不要继续。
        # 放在动作节点出口的话，"步数用尽"和"目标达成"要在三个地方各判一次。
        graph.add_conditional_edges(
            "look", self._route, {"retrieve_memory": "retrieve_memory", END: END}
        )
        graph.add_edge("retrieve_memory", "think")
        graph.add_conditional_edges(
            "think", self._dispatch, {i.value: i.value for i in Intent}
        )
        for intent in Intent:
            # `press` 多绕一步 remember 才回 look；另外两类世界没动，直接回。
            graph.add_edge(intent.value, "remember" if intent is Intent.PRESS else "look")
        graph.add_edge("remember", "look")
        return graph.compile()

    def _nodes(self) -> dict[Intent, Any]:
        """intent → 节点函数。**写成一张表**，漏一类当场 KeyError。

        散在 `add_node` 调用里的话，加了枚举值忘了加节点，症状是运行到一半
        LangGraph 报"未知节点"——离病因隔了一层。
        """
        return {
            Intent.PRESS: self._press,
            Intent.PUSH_GOAL: self._push_goal,
            Intent.INSPECT: self._inspect,
        }

    def _look(self, state: LoopState) -> dict[str, Any]:
        """看一眼，然后决定要不要接着走。**每一步都从这里开始。**

        开局那一帧也走这里——它是图的入口。所以"起点存档就已经满足判据"
        这种 episode 会在第 0 步就被判出来，一步都不用走。
        不这样的话这类局会白跑满步数，而成功率里少掉的正是最容易达成的那些。
        """
        obs, goals, succeeded, why = self._observe(state)
        out = {"observation": obs, "goals": goals, "succeeded": succeeded, "why": why}
        if obs.done:
            return out | {"outcome": self._outcome(state, obs, why)}
        return out | {"space": self._space(goals)}

    def _space(self, goals: list[Goal]) -> ActionSpace:
        """按键由工具层给，**intent 由这里给**。

        能不能再拆一层取决于栈有多深，那是循环的账，工具层不知道。
        栈满了就把 `push_goal` 摘掉——**不是靠 prompt 劝它别拆**。
        说明和可选项必须一致，否则模型会去选一个用不了的东西，
        白花一轮再吃一条 IllegalAction。
        """
        intents = [Intent.PRESS, Intent.INSPECT]
        if len(goals) < MAX_GOAL_DEPTH:
            intents.insert(1, Intent.PUSH_GOAL)
        return self._game.get_action_space().model_copy(update={"intents": intents})

    def _retrieve_memory(self, state: LoopState) -> dict[str, Any]:
        """查这一步要用的**全部**记忆，交给 `think`。**图上单独一格。**

        查什么、查几条本身就是循环控制的决策（用哪种检索、限几条），
        不该藏在 `think()` 内部的一行代码里——独立成节点之后，以后想换策略
        （比如从字符重叠换成 embedding），改的是这一个节点，
        `think()`/`brain.choose()` 的签名都不用动。

        用当前快照的渲染文本去查，不用 `obs.summary`：记忆里存的是快照
        （位置/概况/地标/通行图），summary 是"你在野外"这种一句话，
        两边词汇几乎不重叠，字符打分会一条都选不中。

        ## `known_objects`/`knowledge` 也在这里查，**不在 `_observe()` 里**

        两者都是语义记忆的读——`known_here()` 按坐标查这张地图互动过的东西，
        `knowledge_base()` 查和坐标无关的通用先验——是"查记忆"，不是"看一眼"。
        放进 `_observe()`（`look` 节点）的话，"每一步先查记忆再决策"这条规则
        就又变回散在两个节点里、图上看不出来，而这正是当初把 `retrieve_memory`
        拆成独立节点要解决的问题。

        代价是它们**发生在 judge 之后**（`_observe()`/`look` 已经判过这一步）——
        这其实是好事，不是坏事：`knowledge` 之前放在 `_observe()` 里时，
        `judge()` 每一层每一步都会看到这段和"这一帧是否达成目标"完全无关的
        游戏机制说明（`known_objects` 因为在 `JUDGE_BLIND` 里躲过了，`knowledge`
        没有），纯粹是浪费判定器的 token。挪到这里之后判定器天然看不到，
        不需要再靠黑名单去挡。

        折算进 `state.observation.facts`（而不是单独一个新字段）是为了不动
        `decide_action.md` 的 `$facts` 渲染逻辑——对 `think()` 而言，这两样东西
        看起来和 `walk_map`/`landmarks` 一样，都是"当前状态的一部分"。
        """
        assert state.observation is not None, "retrieve_memory before look"
        obs, ep, step = state.observation, state.episode_id, state.observation.step
        memories = self._memory.query_episodic(
            Snapshot.of(obs).render(), limit=MEMORY_RECALL_LIMIT
        )

        known = self._memory.known_here(obs)
        if known:
            obs = obs.model_copy(update={"facts": {**obs.facts, "known_objects": known}})
        knowledge = self._memory.knowledge_base()
        if knowledge:
            obs = obs.model_copy(update={"facts": {**obs.facts, "knowledge": knowledge}})

        # 检索发生在决策模型调用之前，事件顺序照实写——**因果顺序**，不是排版偏好。
        self._trace.append(*trace_utils.memory_read(ep, step, memories, known, knowledge))
        return {"observation": obs, "memories": memories}

    def _think(self, state: LoopState) -> dict[str, Any]:
        """大脑推理，然后**把它交回来的账翻译成事件**。

        大脑一次 `choose()` 里可能调好几次模型（解析失败要重试），
        所以这里写出来的是一组事件而不是一条。三类分开写，因为它们回答不同的问题：

            MODEL_CALL    每次尝试花了多少 —— 失败的那几次同样烧了钱
            ERROR         每次为什么失败   —— 按 kind 聚合就是失败模式分布
            THINK         最终选了什么     —— 决策内容本身

        `MEMORY_READ` **不在这里写**——查记忆这件事本身已经挪到了图上单独一格
        `retrieve_memory`，那条事件也跟着挪过去了（见该方法）。`state.memories`
        就是那一格交出来的结果，这里直接用，不重新查一遍。

        失败：重试用尽时抛 `MaxRetriesExceeded`。**抛异常的是这里，不是大脑**——
        大脑只汇报"一次都没解析出合法动作"，而"这一局是否因此终止"是循环的判断。
        """
        assert state.observation is not None, "think before look"
        assert state.space is not None, "think without an action space"
        ep, step = state.episode_id, state.observation.step

        decision = self._brain.choose(
            state.goals, state.observation, state.space, state.memories
        )
        assert decision.calls, "choose() must report at least one model call"

        for call in decision.calls:
            for args in trace_utils.model_call(ep, step, Source.DECISION, call):
                self._trace.append(*args)

        if decision.action is None:
            last = decision.calls[-1]
            self._trace.append(*trace_utils.decision_failed(ep, step, last))
            raise MaxRetriesExceeded(len(decision.calls), last.error)

        self._trace.append(*trace_utils.think(ep, step, decision.action, attempt=len(decision.calls)))
        return {"action": decision.action}

    def _dispatch(self, state: LoopState) -> str:
        assert state.action is not None, "dispatch without an action"
        return state.action.intent.value

    # ---- 三个动作节点。**只有 press 推进世界。** ----

    def _press(self, state: LoopState) -> dict[str, Any]:
        """按键，推进世界。**只管执行和账，不写记忆。**

        记忆写入挪到了紧跟着的 `_remember()`——图上能直接看出
        "press 之后必然跟着 remember"，不用再靠读代码才知道这一步顺手把
        记忆也写了。`step` 也不在这里加：`press → remember` 是一个整体，
        加一次的地方在链路末尾（`_remember`），这样 `ACT`/`MEMORY_WRITE`
        才会落在同一个（第 n）步上。
        """
        assert state.observation is not None, "press before look"
        assert state.action is not None, "press without an action"
        ep, before, action = state.episode_id, state.observation, state.action

        result = self._game.execute(action)
        assert result.observation is not None, "execute() must return the new observation"

        # `result.calls` 是推进这一步期间（通常是执行后重新感知那一次）产生的
        # 模型调用记录，**这一步的账当场记，不再拖到下一步 `_observe()` 才补记**——
        # calls 现在跟着 `execute()` 的返回值一起交出来，不用再靠 `drain_calls()`
        # 那种"下次谁来取谁就顺手把上一步的账也记了"的隐式时机。
        for call in result.calls:
            failed = call.get("ok") != "True"
            for args in trace_utils.model_call(
                ep, before.step, Source.PERCEPTION,
                ModelCall(
                    payload=call,
                    error_kind="PerceptionParseFailure" if failed else "",
                    error=call.get("raw", "")[:200] if failed else "",
                ),
            ):
                self._trace.append(*args)

        self._trace.append(*trace_utils.act(ep, before.step, action, result.message))

        # 新观测交给 `_remember()`：它没盖过章（step 恒 0），
        # 但记忆只取 `Snapshot`——那里面全是 facts，和步号无关。
        return {"press_result": result.observation}

    def _remember(self, state: LoopState) -> dict[str, Any]:
        """把 `press` 刚推进的这一步写进记忆。**图上单独一格，只跟在 press 后面。**

        从 `_press()` 里拆出来，是为了让"记忆写在哪个节点"在图上看得见——
        以前一个 `press` 方框里塞了按键、情景记忆落库、语义记忆建档三件事，
        图上读不出这三件事的先后关系，也读不出"只有推进世界那一步才写记忆"这条规则
        （`push_goal`/`inspect` 世界没变，`after` 和 `before` 是同一帧，
        写进去就是一堆"结果：什么都没发生"，会把检索结果稀释掉——所以它们不接这一格）。

        `ACT`（在 `press` 里）和 `MEMORY_WRITE`（这里）都属于第 n 步；
        `step + 1` 放在这里、这条链路的末尾，下一轮 `look` 写的 `OBSERVE`
        才落在第 n+1 步上。提前加一的话事件流的步号会往回跳，
        读日志的人会把这条记忆读成下一步的。
        """
        assert state.observation is not None, "remember before look"
        assert state.action is not None, "remember without an action"
        assert state.press_result is not None, "remember before press"
        ep, before, action, after = (
            state.episode_id, state.observation, state.action, state.press_result
        )

        # `episode_id` 在这里盖：大脑不知道自己在哪一局。
        entry = self._brain.reflect(before, action, after).model_copy(
            update={"episode_id": ep}
        )
        self._memory.write_episodic(entry)
        self._trace.append(*trace_utils.memory_write(ep, before.step, entry))

        # **语义记忆和情景记忆是两回事，分开写。**
        # 情景记忆记"我在那种画面里选了什么"，作用域是一次经过；
        # 这一条记"地图39 x=2 y=3 那个人会说什么"，作用域是那一格，域内恒真、域会再现。
        # 它不需要模型判断——面朝哪一格是 `place + facing` 算出来的，两个输入都确定。
        for note in self._memory.note_step(before, action, after):
            self._trace.append(*trace_utils.object_note(ep, before.step, note))

        return {"step": state.step + 1}

    def _push_goal(self, state: LoopState) -> dict[str, Any]:
        """把一个子目标压进栈。**世界不动，但仍然算一步。**

        算一步是刻意的：它同样烧了一次决策调用。不算的话 `max_steps` 就管不住
        "一直拆、从不走"这种局——而那正是目标栈最容易出的毛病。
        """
        assert state.observation is not None, "push_goal before look"
        assert state.action is not None and state.action.goal is not None
        goal = state.action.goal

        assert len(state.goals) < MAX_GOAL_DEPTH, (
            "push_goal past MAX_GOAL_DEPTH — _space() should have masked it out"
        )
        self._trace.append(*trace_utils.goal_push(
            state.episode_id, state.observation.step, len(state.goals),
            goal, state.action.rationale,
        ))
        return {"goals": [*state.goals, goal], "step": state.step + 1}

    def _inspect(self, state: LoopState) -> dict[str, Any]:
        """对同一帧再问一次视觉模型。**世界不动，但仍然算一步。**

        `INSPECT` 和 `OBSERVE` 是两个事件类型：后者每步必发，前者是大脑主动要的。
        混成一类就算不出"它多久要细看一次"，而那是判断这个动作值不值那次钱的依据。
        """
        assert state.observation is not None, "inspect before look"
        assert state.action is not None and state.action.focus
        focus = state.action.focus

        result = self._game.inspect(focus)
        calls = result.calls
        for call in calls:
            for args in trace_utils.model_call(
                state.episode_id, state.observation.step, Source.PERCEPTION,
                ModelCall(payload=call, error_kind="" if call.get("ok") == "True"
                          else "InspectFailed", error=call.get("raw", "")),
            ):
                self._trace.append(*args)
        self._trace.append(*trace_utils.inspect(
            state.episode_id, state.observation.step, focus,
            calls[-1].get("raw", "") if calls else "",
        ))
        return {"step": state.step + 1}

    def _route(self, state: LoopState) -> str:
        assert state.observation is not None, "routing before any observation"
        return END if state.observation.done else "retrieve_memory"

    # ---- 观测：全项目唯一产出 Observation 的地方 ----

    def _observe(self, state: LoopState) -> tuple[Observation, list[Goal], bool, str]:
        """读一帧，盖上步号与终止判断，判一次成败，记进 trace。

        返回 `(观测, 弹栈之后的目标栈, 是否已达成, 达成的依据)` —— 后三项要写回 state。

        只有 `_look` 调它，所以**一步恰好一次**。这一版之所以不需要
        `_traced_step` / `_judged_step` 那两个去重字段，原因就是这一句。

        `game.perceive()` 是纯读且按帧缓存：`act` 里 `execute()` 刚感知过的那一帧，
        这里命中缓存，**不产生任何额外的模型调用**——`result.calls` 那时是空列表，
        这一步就没有 MODEL_CALL(perception) 事件，因为确实没有调用发生
        （执行阶段真正产生的那些调用，已经在 `_press()` 里当场记过账了）。

        终止有三个来源，这里全判了：

        - **步数用尽** —— 只有这一层知道走了几步。
        - **世界不可用**（窗口被关）—— world 自己置 `done`，这里保留。
        - **栈底那条目标达成** —— 问大脑，见 `_judge`。

        事件顺序是**因果顺序**：先记产生这一帧观测的那几次感知调用，
        再记观测本身，最后才是基于它的判定。反过来记的话，拿事件流做 replay
        的人会先看到结果、再看到产生它的原因。控制台上排版不好看是**显示层的问题**，
        在显示层解决——不能为了排版去改事件流，trace 是唯一的事实来源。

        ## `known_objects`/`knowledge` **不在**这里拼

        它们是语义记忆的读，属于"查记忆"，不属于"看一眼"——放在 `_retrieve_memory()`
        里（图上单独一格），不放在这里。`_observe()` 只产出**这一帧模拟器/视觉模型
        实际给出的东西**，见该方法的完整说明。
        """
        perceived = self._game.perceive()
        raw = perceived.observation
        obs = raw.model_copy(update={
            "step": state.step,
            "done": raw.done or state.step >= state.task.max_steps,
        })

        # **看到的都建档**，没互动过的也建——"这里有一扇门，我见过 7 次一次没进过"
        # 正是这份档案最有用的一类条目。放在这里是因为 `_observe()` 是全项目
        # 唯一一步产出一次观测的地方，而 `seen` 必须一步只加一次。
        self._memory.see_objects(obs, f"{state.episode_id}#{obs.step}")

        for call in perceived.calls:
            # **`ok=False` 的那几次要带上 error_kind**，`trace_utils.model_call()`
            # 才会吐出那条 ERROR。漏掉的话「视觉模型输出解析失败」这一类**永远不出现在失败模式
            # 分布里**，只能回头去解析 payload 里的 `ok` 字符串——而那正是
            # 把 kind 单独拎出来要避免的事。
            failed = call.get("ok") != "True"
            for args in trace_utils.model_call(
                state.episode_id, obs.step, Source.PERCEPTION,
                ModelCall(
                    payload=call,
                    error_kind="PerceptionParseFailure" if failed else "",
                    error=call.get("raw", "")[:200] if failed else "",
                ),
            ):
                self._trace.append(*args)
        # **`goals` 记的是这一帧被看到时的栈**（judge 弹栈之前），因为 OBSERVE
        # 必须先于本步的判定事件（因果顺序，见上）——判完之后的栈会在随后的
        # GOAL_POP 里体现。往 payload 里塞什么字段是 `trace_utils.observe()`
        # 自己的事，这里只交出发生了什么。
        self._trace.append(
            *trace_utils.observe(state.episode_id, obs, state.goals, self._game.last_frame_sha)
        )
        return self._judge(state, obs)

    def _judge(
        self, state: LoopState, obs: Observation
    ) -> tuple[Observation, list[Goal], bool, str]:
        """**每层各判一次（并发），最深的那条"已完成"连同它上面的全部出栈。**

        一条规则，没有特例。

        ## 为什么是"最深的那条已完成"

        子目标是**为了它下面那条**才拆出来的。所以只要某一层完成了，
        它上面那些的存在理由就没了——`[任务, 走到门口, 绕过树]` 里
        "走到门口"完成的那一刻，"绕过树"就是白干，不该再花一步去做它。

        早一版是"先判栈底，再从栈顶往下弹"，两段特殊逻辑，而且**漏掉中间层**：
        栈是 `[任务, A, B]` 时只判了任务和 B，A 完成了也发现不了，
        于是继续做一个已经没有意义的 B。

        ## 栈底那条必然每步都判

        它是其中一层，所以自动每步都判。这一点不能退：任务完全可能顺手完成
        （压着"走到门口"往那边走，路上母亲先说话了）。只判栈顶的话这类局会被记成
        max_steps_exceeded——**成功率被系统性地压低，方向还很难看**。

        ## 只有栈底那条写 success

        子目标是 agent 自己定的。如果它完成也能写 success，agent 就可以压一个
        "我已经到家了"的子目标让判定器判它完成——成功率变成它自己发的奖状。
        这条落在下面的 `if depth == 0`，不是一句注释。

        **`obs.done` 不是跳过的理由**（那里的 `done` 是"步数用尽"，
        而任务完全可能恰好在最后一步达成）；**判过成功之后不再问**
        （结论不会反悔——"已经和母亲说过话了"不会因为多走一步就变回没说过）。
        """
        if state.succeeded:
            # **早退也要把 done/success 打上。** 当前图里走不到这个分支
            # （判成成功的那一步同时置了 `obs.done`，`_route` 直接走 END），
            # 但 resume 会：从一个 `succeeded=True` 的 checkpoint 恢复时，
            # 不打标记的话 `_look` 不出 outcome，转而进 `think`，
            # 而那时 `goals` 已经是空的（成功那一步清空了）——`brain.choose`
            # 的 `assert goals` 当场崩掉。
            return (
                obs.model_copy(update={"done": True, "success": True}),
                state.goals, True, state.why,
            )

        goals = list(state.goals)
        assert goals, "the goal stack must never be empty"

        verdicts = self._judge_all(state.episode_id, goals, obs)
        # **判定的账单单独记**（`Source.JUDGE`）。它和决策各自烧 token，混在一起
        # 就说不清"成功率这个数字本身花了多少钱"，也算不出判定器自己的失效率。
        # 判定失败会顺带补一条 ERROR —— "判了没完成"和"根本没判出来"必须分得开，
        # 否则判定器坏掉的时候，表现就是成功率悄悄变成 0，而没人知道为什么。
        for depth, verdict in enumerate(verdicts):
            for args in trace_utils.judge_call(state.episode_id, obs.step, depth, verdict.call):
                self._trace.append(*args)

        done_at = next((d for d, v in enumerate(verdicts) if v.done), None)
        if done_at is None:
            return obs, goals, False, ""

        # 这一层完成 → 它和它上面的全部出栈。**从上往下记**，读日志的人看到的
        # 顺序和栈的形状一致：先作废最外层，再收掉完成的这一层。
        for gone in range(len(goals) - 1, done_at, -1):
            self._trace.append(*trace_utils.goal_pop(
                state.episode_id, obs.step, gone, goals[gone],
                "superseded", f"第 {done_at} 层已完成，它不再有意义",
            ))
        why = verdicts[done_at].why
        self._trace.append(
            *trace_utils.goal_pop(state.episode_id, obs.step, done_at, goals[done_at], "done", why)
        )

        remaining = goals[:done_at]
        if done_at == 0:
            # 栈底完成 = 任务完成。**只有这一条路径写 success。**
            return (
                obs.model_copy(update={"done": True, "success": True}),
                remaining, True, why,
            )
        return obs, remaining, False, ""

    def _judge_all(
        self, episode_id: str, goals: list[Goal], obs: Observation
    ) -> list[Verdict]:
        """并发判每一层，**按栈的顺序返回**。

        ## 为什么是并发，而不是把整栈塞进一次调用

        直觉的省法是"一次问完所有目标"。那样确实少了几次调用，但会丢两样东西：

        - **判定之间的隔离。** 现在每条目标各判各的，模型看不到别的目标。
          合成一次之后它同时看到任务目标和子目标，就会开始互相推理
          （"子目标完成了，那任务应该也快了"）——污染源只是从"决策模型"
          换成了"栈上的其他目标"，性质一样。
        - **可标定性。** 单目标判定是干净的二分类：`(目标, 判据, 帧) → 0/1`，
          拿人工标注一批就能算准确率。合成一次之后输出是长度可变的向量，
          而且**同一份 prompt 在栈深 1 和栈深 4 下不是同一个东西**——
          误差不再独立，算出来的数没法解释。

        而这几次调用**天然独立**（每次只看一条目标和同一帧画面），
        所以并发就够了：延迟是 `max` 而不是 `sum`，和合成一次一样快。
        合并省的是 token，不是时间——而 token 那一头由 prompt 的字段顺序解决：
        `judge_success.md` 把固定说明和画面放在前面、目标放在最后，
        同一步内这几次调用共享一大段前缀，重复的 input 基本免费。

        ## 两个实现约束

        - **模型调用并发，写 trace 不并发。** `TracePort.append` 要分配单调的
          event_id，多线程写进去就会乱序甚至重号，而 SSE 的断线补发完全依赖它。
          所以这里只并发拿结果，记账回到主线程按 depth 顺序做。
        - **不再有提前退出。** 顺序版判到第一条完成的就停，能省几次调用；
          并发版全判。用 token 换墙钟，这是这次改动明确选的那一边。
        """
        # **同一份历史发给每一层**，不按层筛。除了"哪一层都可能需要那几帧"之外
        # 还有个实际理由：它落在同一步内这几次调用**共享的前缀**里，
        # 重复的 input token 基本免费。按层裁剪反而会把前缀切碎。
        history = self._memory.recent(episode_id, JUDGE_HISTORY)
        if len(goals) == 1:
            return [self._brain.judge(goals[0], obs, history)]

        with ThreadPoolExecutor(max_workers=len(goals)) as pool:
            return list(pool.map(lambda g: self._brain.judge(g, obs, history), goals))

    # ---- 收尾 ----

    def _outcome(self, state: LoopState, obs: Observation, why: str) -> EpisodeOutcome:
        assert obs.done, "_outcome() called before the episode finished"

        reason = ("success" if obs.success
                  else "max_steps_exceeded" if obs.step >= state.task.max_steps
                  else "world_ended")
        result = EpisodeOutcome(
            episode_id=state.episode_id, task_id=state.task.task_id,
            success=obs.success, steps=obs.step, reason=reason,
        )
        self._trace.append(*trace_utils.episode_end(state.episode_id, result, why))
        return result
