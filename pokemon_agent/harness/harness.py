"""Harness —— **控制一局怎么跑**：一张 LangGraph 状态图，加上它的记账。

    look → retrieve_memory → think → press → remember → look
      └─(done)→ summarize → END        （回到 run() 写 EPISODE_END）

三个角色，边界不重叠：`LoopState` 拥有"这一局跑到哪了"（`step` 在那里盖章，
别人只读）；`Harness` 自己**没有任何字段**，只做生死判断与记账；
图只管循环调度与状态传递，记忆层和判定全是自己实现的。

**只有 Harness 调 `trace.append()`**，但不自己拼 payload——组装在
`trace/utils.py` 的纯函数里。这里只决定"这一步该不该记、记成哪个 `EventType`"。

**`press` 是唯一推进世界的节点。** `retrieve_memory`/`remember`/`summarize` 摆成
独立的格子，是为了让三条规则成为图结构本身：每步先查记忆再决策、只有推进世界那步
才写记忆、一局只在结束时蒸馏一次。收尾（`EPISODE_END`）不在图里而在 `run()`，
好让正常结束和异常终止共用一个出口。

完整的设计论证——改名的由来、目标栈为什么退回一层、多层并发判定当初的权衡、
状态为什么全在 `LoopState` 里、光有它为什么还复现不了——见
`docs/spec/harness/SPEC.md`。**那里是"为什么"的唯一去处，这里只说"是什么"。**
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_permission import initialize
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.interfaces.brain import BrainPort
from pokemon_agent.interfaces.tools import GameToolPort, MemoryToolPort
from pokemon_agent.interfaces.trace import TracePort
from pokemon_agent.schemas.action import Action, ActionSpace, Goal
from pokemon_agent.schemas.memory_episode import EpisodeMemory
from pokemon_agent.schemas.memory_episodic import MemoryEntry, Snapshot
from pokemon_agent.schemas.observation import Observation
from pokemon_agent.schemas.task import Task
from pokemon_agent.schemas.trace import EpisodeOutcome, ModelCall, Source, Verdict
from pokemon_agent.trace import utils as trace_utils


MEMORY_RECALL_LIMIT = 5
"""每次决策检索几条情景记忆。原来是 `Brain` 构造时的 `memory_limit` 参数——
大脑不再持有检索通道之后，"查几条"变成了循环控制的事，搬到这里来。
"""

EPISODE_MEMORY_RECALL_LIMIT = 3
"""每次决策检索几条跨局摘要记忆。比 `MEMORY_RECALL_LIMIT` 小：这是"别的局
蒸馏出的经验"，本来就该比"这一局刚发生的事"占更少的 prompt 篇幅。
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

class LoopState(BaseModel):
    """一局的**全部**可序列化状态。

    分两组，但两组都在这里——分组只是为了读的人知道哪些跨步、哪些不跨：

        身份    episode_id / task / step / succeeded / why   跨步，checkpoint 要的就是它
        流转    observation / space / action                  单步内，从一个节点传到下一个

    **`outcome` 不在这里。** 它是这一局的最终结论，由 `run()` 在图跑完之后
    从 `observation` 直接算出来——放进 state 就得有个节点负责填它，
    而"下结论"不该是任何一个循环节点的副业（详见 `run()` 里的说明）。

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

    只在 `press → remember` 这一段之间有意义，
    `remember` 结束后被下一轮 `look` 写的新 `observation` 盖过去，不跨步存活。
    """


class Harness:
    """一局的控制器。**它自己没有状态**——状态全在 `LoopState` 里流。"""

    def __init__(
        self, game: GameToolPort, memory: MemoryToolPort,
        brain: BrainPort, trace: TracePort, run_id: str = "local",
        episode_state_dir: Path | None = None,
    ) -> None:
        """接好四个端口，编译好状态图，此后不再变。"""
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
        self._run_id = run_id
        self._episode_state_dir = episode_state_dir
        """蒸馏跨局摘要记忆（`MemoryTool.summarize_episode`）时要标在
        `EpisodeMemory.run_id` 上——`TracePort` 的实现自己持有一份同样的
        `run_id`（见 `interfaces/trace.py`），但那个不对调用方暴露 getter，
        `Harness` 只能自己另外持有一份。默认值和 `LocalTrace(run_id="local")`
        的默认值保持一致，避免两处默认值打架。
        """
        self._graph = self._compile()

    # ---- 对外只有这一个入口 ----

    @initialize
    def run(self, episode_id: str, task: Task) -> EpisodeOutcome:
        """跑完一局。

        前置条件：episode_id 非空、task.max_steps > 0。
        后置条件：trace 里恰好多一条 EPISODE_START 和一条 EPISODE_END。

        开局、跑图、收尾三段，异常路径也补齐 EPISODE_END 后原样抛出。
        """
        assert episode_id, "run() got an empty episode_id"
        assert task.max_steps > 0, f"max_steps must be > 0, got {task.max_steps}"

        # `_begin()` 也在 try 里面：它 `save_state()`，而那条权限要人类审批，
        # 拒批的异常从这里逃走的话这一局连 `EPISODE_END` 都没有。
        try:
            state = self._begin(episode_id, task)
            # 一步五个节点，留一倍余量——撞上递归上限的症状是一局无声截断。
            final = self._graph.invoke(state, {"recursion_limit": task.max_steps * 6 + 20})
        except Exception as exc:
            # **异常逃出去之前必须补上 EPISODE_END**，否则这一局在事件流里没有结束，
            # 既不算成功也不算失败，直接从成功率的分母上消失。补完照常抛。
            # 不按异常类型分支（包括权限异常）：分类是 `episode_error()` 的职责。
            self._trace.append(*trace_utils.episode_error(episode_id, task.task_id, exc))
            raise

        final_state = LoopState.model_validate(final)
        obs = final_state.observation
        # `outcome` 和下面那条 `EPISODE_END` 是**同一份信息的两个形态**，
        # 所以从同一个 `obs` 派生、写在相邻几行——算在两个地方会静默漂移，
        # 而漂移时返回值说成功、事件流说失败，没有任何东西会报错。
        reason = ("success" if obs.success
                  else "max_steps_exceeded" if obs.step >= task.max_steps
                  else "world_ended")
        outcome = EpisodeOutcome(
            episode_id=episode_id, task_id=task.task_id,
            success=obs.success, steps=obs.step, reason=reason,
        )

        # 正常结束与异常终止共用这一条出口，免得有一条路径漏写。
        self._trace.append(
            *trace_utils.episode_end(episode_id, outcome, final_state.why)
        )
        return outcome

    def _begin(self, episode_id: str, task: Task) -> LoopState:
        """开一局：写下边界，重置世界，造出初始状态。

        **这里不观测**——观测是 `look` 的事，而 `look` 是图的入口。
        记忆**不清空**：跨任务复用经验正是要验证的东西。

        写 EPISODE_START、reset 世界、存起点存档，返回初始 LoopState。
        """
        # **在做任何事之前就写。** `reset()` 和 `save_state()` 都可能抛，
        # 抛在这一行之前的话事件流里会出现一个没有开头的结尾。
        self._trace.append(
            *trace_utils.episode_start(episode_id, task, self._memory.episode_step_count)
        )

        reset = self._game.reset(task)
        if self._episode_state_dir is not None:
            self._game.save_state(str(self._episode_state_dir / f"{episode_id}.start.state"))

        # 当场记账，不留到下一次 `_observe()` 才补记。
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
        # 栈底是任务目标本身，也是成败的唯一依据。
        return LoopState(
            episode_id=episode_id, task=task,
            goals=[Goal(goal=task.goal, criteria=task.success_criteria)],
        )

    # ---- 图 ----

    def _compile(self) -> CompiledStateGraph:
        """装配状态图。

        六个节点、一条终止分支（在 `look` 出口），形状见模块 docstring。
        为什么是这个形状，见 `docs/spec/harness/SPEC.md` 第 3 节。

        注册六个节点与它们之间的边，返回编译好的图。
        """
        graph = StateGraph(LoopState)
        graph.add_node("look", self._look)
        graph.add_node("retrieve_memory", self._retrieve_memory)
        graph.add_node("think", self._think)
        graph.add_node("press", self._press)
        graph.add_node("remember", self._remember)
        graph.add_node("summarize", self._summarize)

        graph.set_entry_point("look")
        # **唯一的终止分支在 look 出口**：看完才知道这一局还要不要继续。
        graph.add_conditional_edges(
            "look",
            lambda state : "summarize" if state.observation.done else "retrieve_memory",
            {"retrieve_memory": "retrieve_memory", "summarize": "summarize"},
        )
        graph.add_edge("retrieve_memory", "think")
        graph.add_edge("think", "press")
        graph.add_edge("press", "remember")
        graph.add_edge("remember", "look")
        graph.add_edge("summarize", END)
        return graph.compile()

    def _look(self, state: LoopState) -> dict[str, Any]:
        """看一眼，然后决定要不要接着走。**每一步都从这里开始。**

        开局那一帧也走这里（它是图的入口），所以"起点存档就已经满足判据"这种
        episode 会在第 0 步就被判出来——不这样的话它们会白跑满步数，
        而成功率里少掉的正是最容易达成的那些。

        返回值是 LangGraph 的**状态增量**（只放这一步改了哪些字段），不是"结果"。

        观测、判定，把新观测与目标栈写回 state；没终止就再取一次动作空间。
        """
        obs, goals, succeeded, why = self._observe(state)

        update: dict[str, Any] = {
            "observation": obs,
            "goals": goals,
            "succeeded": succeeded,
            "why": why,
        }

        if not obs.done:
            # 动作空间由工具层给全，Harness 不再覆写。
            update["space"] = self._game.get_action_space()

        return update

    def _look_route(self, state: LoopState) -> str:
        """路由：终止去蒸馏，否则接着跑。**不直接连 END**——见 `_compile`。"""
        assert state.observation is not None, "routing before any observation"



    def _retrieve_memory(self, state: LoopState) -> dict[str, Any]:
        """查这一步要用的**全部**记忆，交给 `think`。**图上单独一格。**

        四类读都在这里：本局单步情景记忆（全量）、语义记忆 object（按坐标）、
        知识库（按内容相关性）、跨局摘要（按场景 + 任务目标）。
        后三类折进 `obs.facts`，对 `think()` 而言它们和 `walk_map` 一样都是
        "当前状态的一部分"，不必动 prompt 的渲染逻辑。

        **不放在 `_observe()` 里**：判定在那之前就跑完了，放过去会让判定模型
        白读这些字段。详见 `docs/spec/harness/SPEC.md` 4.4。

        查四类记忆、折进观测、写一条 MEMORY_READ，交给下一格。
        """
        assert state.observation is not None, "retrieve_memory before look"
        obs, ep, step = state.observation, state.episode_id, state.observation.step
        memories = self._memory.query_episode_steps(ep)

        known = self._memory.query_objects(obs)
        if known:
            obs = obs.model_copy(update={"facts": {**obs.facts, "known_objects": known}})
        knowledge_result = self._memory.query_knowledge(
            query=state.task.goal, limit=MEMORY_RECALL_LIMIT
        )
        knowledge = "\n\n".join(knowledge_result.contents)
        if knowledge_result.contents:
            obs = obs.model_copy(update={"facts": {**obs.facts, "knowledge": knowledge}})

        # 查询词用 `task.goal` 不是当前快照：`EpisodeMemory` 里没有位置/地标字段，
        # 拿快照去比一条都选不中。`obs.place` 为 None 时没有场景可过滤，跳过。
        episode_memories: list[EpisodeMemory] = []
        if obs.place is not None:
            scene_key = "|".join(filter(None, (
                f"map:{obs.place.map_id}",
                f"scene:{obs.facts.get('scene', '')}",
                f"overlay:{obs.facts.get('overlay', '')}",
            )))
            episode_memories = self._memory.query_episode_summaries(
                scene=scene_key, query=state.task.goal,
                limit=EPISODE_MEMORY_RECALL_LIMIT,
            )
            if episode_memories:
                rendered = "\n\n".join(m.render() for m in episode_memories)
                obs = obs.model_copy(
                    update={"facts": {**obs.facts, "episode_memories": rendered}}
                )

        # 检索先于决策调用，事件顺序照实写——因果顺序，不是排版偏好。
        self._trace.append(
            *trace_utils.memory_read(
                ep, step, memories, known, knowledge, episode_memories,
                knowledge_sources=knowledge_result.sources,
            )
        )
        return {"observation": obs, "memories": memories}

    def _think(self, state: LoopState) -> dict[str, Any]:
        """大脑推理，然后**把它交回来的账翻译成事件**。

        一次 `choose()` 里可能调好几次模型（解析失败要重试），所以这里写出来的是
        一组事件：`MODEL_CALL` 回答"每次花了多少"，`ERROR` 回答"每次为什么失败"，
        `THINK` 回答"最终选了什么"——三个不同的问题，不合并。

        重试用尽时**这里**抛 `MaxRetriesExceeded`：大脑只汇报"没解析出合法动作"，
        而"这一局是否因此终止"是循环的判断。

        调一次大脑，把它的账记进 trace，选出的动作写回 state。
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

    # ---- 唯一的动作节点。**只有 press 推进世界。** ----

    def _press(self, state: LoopState) -> dict[str, Any]:
        """按键，推进世界。**只管执行和账，不写记忆。**

        `step` 也不在这里加：`press → remember` 是一个整体，加一次的地方在链路末尾，
        这样 `ACT` 和 `MEMORY_WRITE` 才落在同一步上。

        执行动作、记这一步的账、写 ACT，把新观测交给 `remember`。
        """
        assert state.observation is not None, "press before look"
        assert state.action is not None, "press without an action"
        ep, before, action = state.episode_id, state.observation, state.action

        result = self._game.execute(action)
        assert result.observation is not None, "execute() must return the new observation"

        # 这一步的账当场记：`calls` 跟着 `execute()` 的返回值一起交出来。
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

        # 新观测没盖过章（step 恒 0），但记忆只取 `Snapshot`，和步号无关。
        return {"press_result": result.observation}

    def _remember(self, state: LoopState) -> dict[str, Any]:
        """把 `press` 刚推进的这一步写进记忆。**只跟在 `press` 后面。**

        两类记忆分开写：情景记忆记"我在那种画面里选了什么"（作用域是一次经过），
        `OBJECT_NOTE` 记"那一格的东西会给什么"（作用域是那一格，域内恒真）。
        后者不需要模型判断——面朝哪一格由 `place + facing` 算出来。

        `step + 1` 放在这条链路末尾，下一轮 `look` 的 `OBSERVE` 才落在第 n+1 步。

        反思成一条记忆、连同语义记忆一起落库，然后步号加一。
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
        self._memory.store_episode_step(entry)
        self._trace.append(*trace_utils.memory_write(ep, before.step, entry))

        # 语义记忆和情景记忆是两回事，分开写；这一条不需要模型判断，
        # 面朝哪一格由 `place + facing` 算出来。
        for note in self._memory.store_objects_interactions(before, action, after):
            self._trace.append(*trace_utils.object_note(ep, before.step, note))

        return {"step": state.step + 1}
    # ---- 观测：全项目唯一产出 Observation 的地方 ----

    def _observe(self, state: LoopState) -> tuple[Observation, list[Goal], bool, str]:
        """读一帧，盖上步号与终止判断，判一次成败，记进 trace。

        全项目**唯一**产出 `Observation` 的地方，而且只有 `_look` 调它——
        "一步恰好一次"是调用图的形状本身保证的，不需要任何去重字段。

        终止的三个来源这里全判了：步数用尽（只有这层知道走了几步）、世界不可用
        （window 被关，world 自己置 `done`）、目标达成（问大脑，见 `_judge`）。

        事件顺序是**因果顺序**：先记产生这一帧的感知调用，再记观测本身，
        最后才是基于它的判定。反过来记，replay 的人会先看到结果再看到原因。

        感知一帧、盖章、记 OBSERVE，然后把判定的活交给 `_judge`。
        """
        perceived = self._game.perceive()
        raw = perceived.observation
        obs = raw.model_copy(update={
            "step": state.step,
            "done": raw.done or state.step >= state.task.max_steps,
        })

        # 看到的都建档，没互动过的也建——"见过 7 次一次没进过"正是最有用的条目。
        # 放在这里是因为 `seen` 必须一步只加一次。
        for call in perceived.calls:
            # `ok=False` 的那几次要带上 `error_kind`，否则「视觉模型解析失败」
            # 这一类永远不出现在失败模式分布里。
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
        # `goals` 记的是**判定弹栈之前**的栈：OBSERVE 必须先于本步的判定事件。
        self._trace.append(
            *trace_utils.observe(state.episode_id, obs, state.goals, self._game.last_frame_sha)
        )
        return self._judge(state, obs)

    def _judge(
        self, state: LoopState, obs: Observation
    ) -> tuple[Observation, list[Goal], bool, str]:
        """**判栈顶那一条。完成就出栈。**

        栈空 = 任务完成，**只有这一条路径写 `success`**。`if not remaining` 在
        栈恒为一层的今天永远成立，留着是为了把这句话写成代码：子目标回来之后，
        agent 自己压的那些完成了只该弹栈，不该给自己发奖状。

        `obs.done` 不是跳过判定的理由（那是"步数用尽"，任务可能恰好在最后一步达成）；
        判过成功之后不再问（结论不会反悔）。

        多层并发判定当初的权衡见 `docs/spec/harness/SPEC.md` 5.1。

        取最近几步当证据，问一次大脑，完成就弹栈并标记这一局结束。
        """
        if state.succeeded:
            # 早退也要把 done/success 打上。当前图里走不到，但 resume 会：
            # 不打标记的话会转而进 `think`，而那时 `goals` 已经空了。
            return (
                obs.model_copy(update={"done": True, "success": True}),
                state.goals, True, state.why,
            )

        goals = list(state.goals)
        assert goals, "the goal stack must never be empty"

        # **同一份历史给判定器。** 证据可能在三步以前那一帧的对话框里。
        history = self._memory.query_recent_steps(state.episode_id, JUDGE_HISTORY)
        verdict = self._brain.judge(goals[-1], obs, history)

        # 判定的账单独记（`Source.JUDGE`），否则算不出"成功率本身花了多少钱"。
        # 判定失败另补一条 ERROR——"判了没完成"和"根本没判出来"必须分得开。
        depth = len(goals) - 1
        for args in trace_utils.judge_call(state.episode_id, obs.step, depth, verdict.call):
            self._trace.append(*args)

        if not verdict.done:
            return obs, goals, False, ""

        self._trace.append(*trace_utils.goal_pop(
            state.episode_id, obs.step, depth, goals[-1], "done", verdict.why
        ))
        remaining = goals[:-1]
        if not remaining:
            # 栈空 = 任务完成。**只有这一条路径写 success。**
            return (
                obs.model_copy(update={"done": True, "success": True}),
                remaining, True, verdict.why,
            )
        return obs, remaining, False, ""

    # ---- 收尾 ----

    def _summarize(self, state: LoopState) -> dict[str, Any]:
        """**图上的最后一格**：把这一局蒸馏成一条跨局摘要记忆。

        摆成节点而不是藏在收尾逻辑里，是因为它**要调一次模型**——图上看得见的
        东西才会被算进成本，藏起来的那次调用不出现在任何方框里。

        只吞 `ValueError` 这一种失败，而且**单据齐全才吞**：蒸馏器内部已经留了一条
        `ERROR` trace 事件，那是它出现在失败模式统计里的凭证。吞掉是因为
        "这一局跑完了"和"没能力提炼经验"是两件事，后者不该拖累前者的 `EPISODE_END`。

        调一次蒸馏、把这一局的经验落库，失败则跳过。
        """
        obs = state.observation
        assert obs is not None and obs.done, "summarize before the episode finished"
        try:
            self._memory.store_episode_summary(
                state.episode_id, self._run_id, state.task.goal,
                {"success": obs.success, "steps": obs.step,
                 "max_steps": state.task.max_steps},
            )
        except ValueError:
            pass
        return {}
