"""`act` 格（run 层）：**派一局**——`dispatch` 选目标、拼 `EpisodeInput`，经
`episode_entry.run_episode` 跑完 episode 子图，把 `EpisodeOutput` 写进 `pending_episode`。

吸收在下一圈的 `perceive`、盖章在 `review_and_judge`；本格出口回 `perceive`（一圈 = 一局）。

**整局抛错由本格接住**（谁接住谁记账，与 episode 层 `act` 接 task 抛错同形）：
补空章（episode 图已经死了，只能由接住它的人代写，保证一局恰好一条 EpisodeMemory）→
记 `episode_error`；`AgentError`（预期内的单局失败）兜成一份 `ERROR` 结算，别的异常原样上抛
（由 `run_entry.new_run` 记 `run_error`）。
episode 子图编译一次、缓存。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from pokemon_agent.errors import AgentError
from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind
from pokemon_agent.schemas.harness.domain import EpisodeInput, EpisodeOutput, Termination

from ...episode import compile_episode_graph, episode_entry
from ...episode.episode_done.leave_chapter import store_empty_chapter
from ...episode.episode_runtime import EpisodeRuntime
from ..run_state import RunState
from ..runtime import RunRuntime
from .dispatch import dispatch

_episode_graph: CompiledStateGraph | None = None


def episode_graph() -> CompiledStateGraph:
    """episode 子图：编译一次、缓存。"""
    global _episode_graph
    if _episode_graph is None:
        _episode_graph = compile_episode_graph()
    return _episode_graph


def act(state: RunState, runtime: Runtime[RunRuntime]) -> dict[str, Any]:
    """派一局，返回 `{"goals", "episode_input", "step", "pending_episode"}`。"""
    # 步骤 1：选目标、盖 RUNNING、拼 EpisodeInput。
    dispatched = dispatch(state)
    episode_input: EpisodeInput = dispatched["episode_input"]

    # 步骤 2：跑 episode 子图，结算交给下一圈 perceive 吸收；抛错由本格接住。
    try:
        outcome = episode_entry.run_episode(
            runtime.context.episode, episode_graph(), episode_input=episode_input
        )
    except Exception as exc:
        outcome = _episode_error(runtime.context.episode, state.run_id, episode_input, exc)
    return {**dispatched, "pending_episode": outcome}


def _episode_error(
    deps: EpisodeRuntime, run_id: str, episode_input: EpisodeInput, exc: Exception
) -> EpisodeOutput:
    """补空章 → 记 `episode_error`；`AgentError` 兜成 `ERROR` 结算，别的原样上抛。"""
    episode_id = episode_input.episode_id
    reason = f"error: {type(exc).__name__}"
    store_empty_chapter(
        deps,
        run_id=run_id,
        episode_id=episode_id,
        goal=episode_input.goal.goal,
        tasks_used=0,
        acts_used=0,
        termination=Termination.ERROR,
        reason=reason,
        source="run.act",
        step=0,
    )
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.EPISODE_ERROR,
            meta={"source": "run.act", "episode_id": episode_id, "task_id": episode_id, "step": 0},
            error=episode_entry.exc_snapshot(exc),
        )
    )
    if not isinstance(exc, AgentError):
        raise exc
    return EpisodeOutput(
        episode_id=episode_id,
        goal_id=episode_input.goal.task_id,
        termination=Termination.ERROR,
        judge_reason="这一局抛错，未经判定",
        reason=reason,
        tasks_used=0,
        acts_used=0,
    )


__all__ = ["act", "dispatch", "episode_graph"]
