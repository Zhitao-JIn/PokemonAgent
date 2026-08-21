"""Harness —— **控制一局怎么跑**。它就是以前那张图。

改名的理由：以前叫 harness 的那个类其实是工具层（大脑怎么碰环境），
而真正在控制循环的是 `graph/build.py`。名字盖住了这个事实，
于是"一步"这个概念没有主人——world 在数 step，harness 在猜边界，
图在决定什么时候算一轮，三家各有一份，才需要按步去重来对账。

现在只有一个主人：

    LoopState 拥有"这一局跑到哪了"。step 在这里盖章，别人只读。
    Harness   拥有生死判断与记账。**它自己没有任何字段**，是无状态的。

**Harness 是唯一写 trace 的人。** 全项目 `trace.append` 只出现在这个文件里。
大脑把账（`ModelCall`）连同结果一起交出来，由这里翻译成事件；
判定器碰不到自己的账不是特权设计，而是所有大脑调用的共同处境。

## 一轮循环长什么样

    look        obs = self._observe(state)    -> MODEL_CALL(感知) + OBSERVE
                                                 + MODEL_CALL(判定)×栈深 + GOAL_POP×弹了几层
                space = self._space(goals)
    think       d = brain.choose(goals, obs, space)
                                              -> MEMORY_READ + MODEL_CALL(决策)×N
                                                 + ERROR×失败次数 + THINK
    ┌ press     tools.execute → reflect → memory_write   -> ACT + MEMORY_WRITE
    ├ push_goal 压一个子目标                              -> GOAL_PUSH
    └ inspect   对同一帧再问一个具体问题                    -> MODEL_CALL(感知) + INSPECT
                                                 三条都 step += 1，然后回到 look

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

import json
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
from pokemon_agent.schemas.memory_episodic import Snapshot
from pokemon_agent.schemas.observation import Observation
from pokemon_agent.schemas.task import Task
from pokemon_agent.schemas.trace import EpisodeOutcome, EventType, ModelCall, Source, Verdict

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
    action: Action | None = None
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
            self._trace.append(
                episode_id, 0, EventType.EPISODE_END, Source.HARNESS,
                {"success": "False", "steps": "-1", "reason": "error",
                 "task_id": task.task_id,
                 "why": f"{type(exc).__name__}: {exc}"[:300]},
            )
            raise

        outcome = LoopState.model_validate(final).outcome
        assert outcome is not None, "the graph must not end without an outcome"
        return outcome

    def _begin(self, episode_id: str, task: Task) -> LoopState:
        """开一局：重置世界，写下边界，造出初始状态。

        **这里不观测**——观测是 `look` 的事，而 `look` 是图的入口。
        记忆**不清空**——跨任务复用经验正是要验证的东西。
        """
        self._game.reset(task)

        # **episode 的边界必须进事件流。** 没有它，光看日志分不出一次尝试从哪开始，
        # 更不知道它带了多少条记忆进来——而那正是 A/B 实验的自变量本身。
        self._trace.append(
            episode_id, 0, EventType.EPISODE_START, Source.HARNESS,
            {"task_id": task.task_id, "goal": task.goal,
             "max_steps": str(task.max_steps),
             "memory_carried": str(self._memory.episodic_size)},
        )
        # 栈底是任务目标本身。**它永远在，也永远是成败的唯一依据。**
        return LoopState(
            episode_id=episode_id, task=task,
            goals=[Goal(goal=task.goal, criteria=task.success_criteria)],
        )

    # ---- 图 ----

    def _compile(self) -> CompiledStateGraph:
        """look → think → (press | push_goal | inspect) → look

        **分派放在图的边上，不是某个节点里的 if。** 这样"agent 能做哪几类事"
        在图上一眼看得见，加一类 = 加一个枚举值 + 一个节点 + 一条边，
        `_think` 和 prompt 的形状都不用动。
        """
        graph = StateGraph(LoopState)
        graph.add_node("look", self._look)
        graph.add_node("think", self._think)
        for intent, node in self._nodes().items():
            graph.add_node(intent.value, node)

        graph.set_entry_point("look")
        # **唯一的终止分支在 look 出口**：看完才知道这一局还要不要继续。
        # 放在动作节点出口的话，"步数用尽"和"目标达成"要在三个地方各判一次。
        graph.add_conditional_edges("look", self._route, {"think": "think", END: END})
        graph.add_conditional_edges(
            "think", self._dispatch, {i.value: i.value for i in Intent}
        )
        for intent in Intent:
            graph.add_edge(intent.value, "look")
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

    def _think(self, state: LoopState) -> dict[str, Any]:
        """大脑推理，然后**把它交回来的账翻译成事件**。

        大脑一次 `choose()` 里可能调好几次模型（解析失败要重试），
        所以这里写出来的是一组事件而不是一条。四类分开写，因为它们回答不同的问题：

            MEMORY_READ   它翻了哪几条经验 —— 「这个决策是被哪条影响的」
            MODEL_CALL    每次尝试花了多少 —— 失败的那几次同样烧了钱
            ERROR         每次为什么失败   —— 按 kind 聚合就是失败模式分布
            THINK         最终选了什么     —— 决策内容本身

        失败：重试用尽时抛 `MaxRetriesExceeded`。**抛异常的是这里，不是大脑**——
        大脑只汇报"一次都没解析出合法动作"，而"这一局是否因此终止"是循环的判断。
        """
        assert state.observation is not None, "think before look"
        assert state.space is not None, "think without an action space"
        ep, step = state.episode_id, state.observation.step

        # **检索发生在这里，不在大脑里。** `Brain.choose()` 不持有任何工具/记忆——
        # 查什么、查几条是循环控制的事。用当前快照的渲染文本去查，不用
        # `obs.summary`：记忆里存的是快照（位置/概况/地标/通行图），summary 是
        # "你在野外"这种一句话，两边词汇几乎不重叠，字符打分会一条都选不中。
        memories = self._memory.query_episodic(
            Snapshot.of(state.observation).render(), limit=MEMORY_RECALL_LIMIT
        )
        decision = self._brain.choose(state.goals, state.observation, state.space, memories)
        assert decision.calls, "choose() must report at least one model call"

        # 检索发生在模型调用之前，事件顺序照实写——**因果顺序**，不是排版偏好。
        self._trace.append(
            ep, step, EventType.MEMORY_READ, Source.DECISION,
            {"count": str(len(decision.recalled)), "refs": " ".join(decision.recalled)},
        )
        for call in decision.calls:
            self._record_call(ep, step, Source.DECISION, call)

        if decision.action is None:
            last = decision.calls[-1]
            self._trace.append(
                ep, step, EventType.ERROR, Source.DECISION,
                {"kind": "MaxRetriesExceeded", "reason": "max_retries_exceeded",
                 "last": f"{last.error_kind}: {last.error}"},
            )
            raise MaxRetriesExceeded(len(decision.calls), last.error)

        self._trace.append(
            ep, step, EventType.THINK, Source.DECISION,
            {
                "thought": decision.action.thought,
                "action": decision.action.name,
                # args 必须记：不记的话分不清「模型没给参数」和「给了但没显示」。
                "args": json.dumps(decision.action.args, ensure_ascii=False),
                # rationale 也记在这里，不只依赖 MEMORY_WRITE ——
                # **无记忆基线组不写记忆**，那时 rationale 只剩这一处落点。
                "rationale": json.dumps(decision.action.rationale, ensure_ascii=False),
                "attempt": str(len(decision.calls)),
            },
        )
        return {"action": decision.action}

    def _dispatch(self, state: LoopState) -> str:
        assert state.action is not None, "dispatch without an action"
        return state.action.intent.value

    # ---- 三个动作节点。**只有 press 推进世界。** ----

    def _press(self, state: LoopState) -> dict[str, Any]:
        """按键、记忆、推进一步。**这一整段的顺序是这个节点的全部意义。**

        `ACT` 和 `MEMORY_WRITE` 都属于第 n 步；`step + 1` 放在最后，
        下一轮 `look` 写的 `OBSERVE` 才落在第 n+1 步上。
        提前加一的话事件流的步号会往回跳，读日志的人会把那条记忆读成下一步的。

        **记忆只在这里写。** `MemoryEntry` 的语义是"我看到 X，因为 Y，做了 Z，
        变成 W"——另外两个节点世界没变，`after` 和 `before` 是同一帧，
        写进去就是一堆"结果：什么都没发生"，会把检索结果稀释掉。
        """
        assert state.observation is not None, "press before look"
        assert state.action is not None, "press without an action"
        ep, before, action = state.episode_id, state.observation, state.action

        result = self._game.execute(action)
        assert result.observation is not None, "execute() must return the new observation"

        self._trace.append(
            ep, before.step, EventType.ACT, Source.WORLD,
            {"action": action.name, "args": json.dumps(action.args, ensure_ascii=False),
             "message": result.message},
        )

        # `after` 用 `execute()` 返回的那一帧。它没盖过章（step 恒 0），
        # 但记忆只取 `Snapshot`——那里面全是 facts，和步号无关。
        # `episode_id` 也是在这里盖的：大脑不知道自己在哪一局。
        entry = self._brain.reflect(before, action, result.observation).model_copy(
            update={"episode_id": ep}
        )
        self._memory.write_episodic(entry)
        self._trace.append(
            ep, before.step, EventType.MEMORY_WRITE, Source.HARNESS,
            {"key": entry.key, "content": entry.render()},
        )

        # **语义记忆和情景记忆是两回事，分开写。**
        # 情景记忆记"我在那种画面里选了什么"，作用域是一次经过；
        # 这一条记"地图39 x=2 y=3 那个人会说什么"，作用域是那一格，域内恒真、域会再现。
        # 它不需要模型判断——面朝哪一格是 `place + facing` 算出来的，两个输入都确定。
        for note in self._memory.note_step(before, action, result.observation):
            self._trace.append(
                ep, before.step, EventType.OBJECT_NOTE, Source.HARNESS,
                {"key": note.landmark.place.key, "kind": note.landmark.kind,
                 "content": note.render()},
            )

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
        self._trace.append(
            state.episode_id, state.observation.step, EventType.GOAL_PUSH, Source.DECISION,
            {"depth": str(len(state.goals)), "goal": goal.goal, "criteria": goal.criteria,
             "rationale": json.dumps(state.action.rationale, ensure_ascii=False)},
        )
        return {"goals": [*state.goals, goal], "step": state.step + 1}

    def _inspect(self, state: LoopState) -> dict[str, Any]:
        """对同一帧再问一次视觉模型。**世界不动，但仍然算一步。**

        `INSPECT` 和 `OBSERVE` 是两个事件类型：后者每步必发，前者是大脑主动要的。
        混成一类就算不出"它多久要细看一次"，而那是判断这个动作值不值那次钱的依据。
        """
        assert state.observation is not None, "inspect before look"
        assert state.action is not None and state.action.focus
        focus = state.action.focus

        self._game.inspect(focus)
        calls = self._game.drain_calls()
        for call in calls:
            self._record_call(
                state.episode_id, state.observation.step, Source.PERCEPTION,
                ModelCall(payload=call, error_kind="" if call.get("ok") == "True"
                          else "InspectFailed", error=call.get("raw", "")),
            )
        self._trace.append(
            state.episode_id, state.observation.step, EventType.INSPECT, Source.PERCEPTION,
            {"focus": focus, "answer": calls[-1].get("raw", "") if calls else ""},
        )
        return {"step": state.step + 1}

    def _route(self, state: LoopState) -> str:
        assert state.observation is not None, "routing before any observation"
        return END if state.observation.done else "think"

    # ---- 观测：全项目唯一产出 Observation 的地方 ----

    def _observe(self, state: LoopState) -> tuple[Observation, list[Goal], bool, str]:
        """读一帧，盖上步号与终止判断，判一次成败，记进 trace。

        返回 `(观测, 弹栈之后的目标栈, 是否已达成, 达成的依据)` —— 后三项要写回 state。

        只有 `_look` 调它，所以**一步恰好一次**。这一版之所以不需要
        `_traced_step` / `_judged_step` 那两个去重字段，原因就是这一句。

        `game.perceive()` 是纯读且按帧缓存：`act` 里 `execute()` 刚感知过的那一帧，
        这里命中缓存，**不产生任何额外的模型调用**——`drain_calls()` 那时返回空列表，
        这一步就没有 MODEL_CALL(perception) 事件，因为确实没有调用发生。

        终止有三个来源，这里全判了：

        - **步数用尽** —— 只有这一层知道走了几步。
        - **世界不可用**（窗口被关）—— world 自己置 `done`，这里保留。
        - **栈底那条目标达成** —— 问大脑，见 `_judge`。

        事件顺序是**因果顺序**：先记产生这一帧观测的那几次感知调用，
        再记观测本身，最后才是基于它的判定。反过来记的话，拿事件流做 replay
        的人会先看到结果、再看到产生它的原因。控制台上排版不好看是**显示层的问题**，
        在显示层解决——不能为了排版去改事件流，trace 是唯一的事实来源。

        ## `known_objects` 在这里拼，不在 `GameTools` 里

        `GameToolPort` 只碰 world，不知道语义记忆的存在。这里拿到 `game.perceive()`
        的原始观测之后，另外问 `memory.known_here()` 要一段渲染好的文字，
        有内容才拼进 `facts["known_objects"]`——两个协议各管各的，组合是这一层的活。
        """
        raw = self._game.perceive()
        obs = raw.model_copy(update={
            "step": state.step,
            "done": raw.done or state.step >= state.task.max_steps,
        })
        known = self._memory.known_here(obs)
        if known:
            obs = obs.model_copy(update={"facts": {**obs.facts, "known_objects": known}})

        # **看到的都建档**，没互动过的也建——"这里有一扇门，我见过 7 次一次没进过"
        # 正是这份档案最有用的一类条目。放在这里是因为 `_observe()` 是全项目
        # 唯一一步产出一次观测的地方，而 `seen` 必须一步只加一次。
        self._memory.see_objects(obs, f"{state.episode_id}#{obs.step}")

        for call in self._game.drain_calls():
            # **`ok=False` 的那几次要带上 error_kind**，`_record_call` 才会补一条
            # ERROR。漏掉的话「视觉模型输出解析失败」这一类**永远不出现在失败模式
            # 分布里**，只能回头去解析 payload 里的 `ok` 字符串——而那正是
            # 把 kind 单独拎出来要避免的事。
            failed = call.get("ok") != "True"
            self._record_call(
                state.episode_id, obs.step, Source.PERCEPTION,
                ModelCall(
                    payload=call,
                    error_kind="PerceptionParseFailure" if failed else "",
                    error=call.get("raw", "")[:200] if failed else "",
                ),
            )
        self._trace.append(
            state.episode_id, obs.step, EventType.OBSERVE, Source.PERCEPTION,
            # **facts 必须进 payload。** 它才是观测的实质内容。只记 summary 的话，
            # replay 出来只剩「你在野外」这种废话，既看不出大脑当时掌握了什么，
            # 也没法回答「决策错是因为没看见还是没想到」。
            #
            # `frame_sha` 同样关键：没有它，一条读错的观测**无法追查**是哪一帧，
            # 阶段 3.2 拿 VLM 输出和真值对标也对不上号。
            {"frame_sha": self._game.last_frame_sha,
             "summary": obs.summary,
             "scene": obs.facts.get("scene", ""), "overlay": obs.facts.get("overlay", ""),
             "facts": json.dumps(obs.facts, ensure_ascii=False)},
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
        # `depth` 进 payload：子目标判得多不代表任务判得多，两种粒度必须分得开，
        # 否则"判定花了多少钱"这个数会被子目标的量淹掉。
        # 判定失败会顺带补一条 ERROR —— "判了没完成"和"根本没判出来"必须分得开，
        # 否则判定器坏掉的时候，表现就是成功率悄悄变成 0，而没人知道为什么。
        for depth, verdict in enumerate(verdicts):
            self._record_call(
                state.episode_id, obs.step, Source.JUDGE,
                verdict.call.model_copy(update={
                    "payload": {**verdict.call.payload, "depth": str(depth)}
                }),
            )

        done_at = next((d for d, v in enumerate(verdicts) if v.done), None)
        if done_at is None:
            return obs, goals, False, ""

        # 这一层完成 → 它和它上面的全部出栈。**从上往下记**，读日志的人看到的
        # 顺序和栈的形状一致：先作废最外层，再收掉完成的这一层。
        for gone in range(len(goals) - 1, done_at, -1):
            self._trace.append(
                state.episode_id, obs.step, EventType.GOAL_POP, Source.JUDGE,
                # **`reason` 要分开**：这些不是完成的，是**失去意义的**。
                # 混成一类就算不出"拆出来的子目标有多少是白拆的"，
                # 而那正是判断目标栈有没有帮上忙的那个数。
                {"depth": str(gone), "goal": goals[gone].goal,
                 "reason": "superseded", "why": f"第 {done_at} 层已完成，它不再有意义"},
            )
        why = verdicts[done_at].why
        self._trace.append(
            state.episode_id, obs.step, EventType.GOAL_POP, Source.JUDGE,
            {"depth": str(done_at), "goal": goals[done_at].goal,
             "reason": "done", "why": why},
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

    # ---- 记账 ----

    def _record_call(
        self, episode_id: str, step: int, source: Source, call: ModelCall
    ) -> None:
        """一次模型调用 → 一条 `MODEL_CALL`，失败的再补一条 `ERROR`。

        **账单和失败模式是两件事**：前者回答"花了多少钱"，后者回答"为什么没拿到东西"。
        混进一条里，按失败类型聚合的时候就得去解析 payload 里的字符串。
        """
        self._trace.append(episode_id, step, EventType.MODEL_CALL, source, call.payload)
        if call.error_kind:
            self._trace.append(
                episode_id, step, EventType.ERROR, source,
                {"kind": call.error_kind, "reason": call.error,
                 "attempt": call.payload.get("attempt", "")},
            )

    def _outcome(self, state: LoopState, obs: Observation, why: str) -> EpisodeOutcome:
        assert obs.done, "_outcome() called before the episode finished"

        reason = ("success" if obs.success
                  else "max_steps_exceeded" if obs.step >= state.task.max_steps
                  else "world_ended")
        result = EpisodeOutcome(
            episode_id=state.episode_id, task_id=state.task.task_id,
            success=obs.success, steps=obs.step, reason=reason,
        )
        # **成功与否必须落进事件流。** 不记的话，光看日志算不出成功率——
        # 而那是这个项目唯一的一组硬数字。
        self._trace.append(
            state.episode_id, obs.step, EventType.EPISODE_END, Source.HARNESS,
            {"success": str(result.success), "steps": str(result.steps),
             "reason": result.reason, "task_id": result.task_id,
             # 判定给的理由要留档：成功率是要报的数字，**每一个 True 都得说得出依据**
             "why": why},
        )
        return result
