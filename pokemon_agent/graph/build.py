"""LangGraph 装配 —— **唯一**知道具体实现是谁的地方。

其余所有模块只认识 Protocol。想知道"这套东西是怎么拼起来的"，只需要读这个文件。

图的形状（对应 ReAct 的三段）：

    observe ──→ think ──→ act ──┬─→ (未结束) 回到 observe
                                └─→ (已结束) END

为什么用 StateGraph 而不是 while 循环：三段之间的转移条件是显式的边，
将来往中间插节点（状态归并、值回填、权限确认）不需要改循环体。
LangGraph 只承担循环调度与状态传递，记忆和状态表全部是自己实现的。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

from pokemon_agent.brain.react import ReActBrain
from pokemon_agent.harness.harness import Harness
from pokemon_agent.interfaces.trace import TracePort
from pokemon_agent.mocks.mock_trace import MockTrace
from pokemon_agent.schemas.core import Action, ActionSpace, EpisodeOutcome, Observation, Task
from pokemon_agent.world.pyboy_world import PyBoyWorld


class AgentState(BaseModel):
    """图的状态载体。

    注意这里存的是**流转中的数据**，不是业务状态——业务状态在 harness 里。
    这个区分很重要：图状态可以被 LangGraph 复制、合并、快照，
    如果把记忆或世界塞进来，那些操作就会产生意料之外的副本。
    """

    episode_id: str
    task: Task
    observation: Observation | None = None
    action_space: ActionSpace | None = None
    action: Action | None = None
    outcome: EpisodeOutcome | None = None
    started: bool = Field(default=False, description="是否已 reset 过世界")


def build_graph(brain: ReActBrain, harness: Harness) -> CompiledStateGraph:
    """把 brain 和 harness 连成一张可执行的图。

    前置条件：两者都已装配好（各自的依赖已注入）。
    返回的对象用 `.invoke(AgentState(...))` 跑一个完整 episode。
    """

    def observe(state: AgentState) -> dict[str, Any]:
        """取观测与动作空间。第一步顺便开 episode。

        进到这里时 episode 必然未结束，两条入边都保证了：
        图入口走 `start_episode()`，它 assert 了 step == 0 且 done 为 False；
        回边由 `should_continue()` 判过 done。所以这里**不做 done 分支**——
        那段代码永远不执行，而且它返回的 `action_space=None` 会让下一个节点的
        assert 崩在更远的地方，是个假防御。
        """
        if not state.started:
            obs = harness.start_episode(state.episode_id, state.task)
        else:
            obs = harness.perceive()

        assert not obs.done, "observe() entered on a finished episode (routing bug)"
        return {"observation": obs, "started": True, "action_space": harness.get_action_space()}

    def think(state: AgentState) -> dict[str, Any]:
        """大脑推理。

        前置条件：observe 已产出观测与动作空间（图的边保证了这点，所以这里 assert）。
        """
        assert state.observation is not None, "think before observe"
        assert state.action_space is not None, "think without an action space"

        action = brain.choose(state.episode_id, state.observation, state.action_space)
        return {"action": action}

    def act(state: AgentState) -> dict[str, Any]:
        """执行动作并写记忆。"""
        assert state.action is not None, "act without an action"
        assert state.observation is not None, "act before observe"

        result = harness.execute(state.action)
        assert result.observation is not None, "world.step() must return the new observation"

        # 顺序是有讲究的，三步都不能换：
        #   execute  → ACT(N)          这一步做了什么
        #   remember → MEMORY_WRITE(N) 这一步学到了什么（结果那一头就是新观测）
        #   settle   → OBSERVE(N+1)    新观测入账，并交给判定器
        # 把 settle 提到 remember 前面，事件流的步号就会 N+1 → N 往回跳。
        obs = result.observation
        brain.remember(state.episode_id, state.observation, state.action, obs)
        obs = harness.settle(obs)

        outcome = harness.outcome(obs) if obs.done else None
        return {"observation": obs, "outcome": outcome}

    def should_continue(state: AgentState) -> str:
        """条件边：episode 结束就退出，否则回到 observe。"""
        assert state.observation is not None, "routing before any observation"
        return END if state.observation.done else "observe"

    graph = StateGraph(AgentState)
    graph.add_node("observe", observe)
    graph.add_node("think", think)
    graph.add_node("act", act)

    graph.set_entry_point("observe")
    graph.add_edge("observe", "think")
    graph.add_edge("think", "act")
    graph.add_conditional_edges("act", should_continue, {"observe": "observe", END: END})

    return graph.compile()


def build_real(
    rom: str,
    state_path: str | None = None,
    *,
    vision_model: str = "qwen3-vl-plus",
    text_model: str = "qwen-plus",
    judge_model: str = "",
    watch: bool = False,
    grid: bool = True,
    trace: TracePort | None = None,
) -> tuple[CompiledStateGraph, Harness, TracePort, PyBoyWorld]:
    """装配真实的一套：PyBoy + 视觉感知 + 真实 LLM + 图。

    **这里是全项目唯一一处 new 具体实现**（CLAUDE.md 第三节第 3 条）。
    曾经还有一个 `build_demo`（MockWorld + FakeLLM，离线跑最小闭环），
    真实环境接进来之后已删除——留着两条装配路径，等于留着一条**没人真的跑**的代码路径。

    两个模型是刻意分开的，不是设计洁癖——它由计费结构决定：
    决策走有资源包的文本模型，感知每步都调、任务简单，走最便宜的视觉模型。
    两个 Port 分开才能分别选型。

    trace 仍是 `MockTrace`（内存列表，不落盘）。落盘、replay、checkpoint
    是阶段 2 的事；在那之前跑出来的数据**进程一退就没了**，只适合调试。
    """
    from pokemon_agent.harness.judge import LLMSuccessJudge
    from pokemon_agent.providers.dashscope import QwenText, QwenVision
    from pokemon_agent.vision.preprocess import GridOverlay

    # 网格是**给模型看的辅助线**，不是画面的一部分——所以它挂在 provider 上，
    # world 交出去的、存证用的、将来给 CV 通道用的，仍然是原图。
    vision = QwenVision(model=vision_model, preprocess=(GridOverlay(),) if grid else ())
    world = PyBoyWorld(rom, vision, state_path=state_path, watch=watch)
    trace = trace or MockTrace()
    # 判定器和大脑**各建一个 provider 实例**，即使型号相同。
    # 共用一个的话，将来想给判定换个更强的模型就得改两处；而且 manifest 里
    # 两条链路的配置会指向同一个对象，看不出它们是可以分别选型的。
    judge = LLMSuccessJudge(QwenText(model=judge_model or text_model))
    harness = Harness(world, trace, judge=judge)
    brain = ReActBrain(QwenText(model=text_model), harness, trace)
    return build_graph(brain, harness), harness, trace, world
