"""`close_episode`：从终态派生 `EpisodeOutput`，写 `output`，落 `EPISODE_END`。"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind
from pokemon_agent.schemas.harness.domain import EpisodeOutput

from ..episode_runtime import EpisodeRuntime
from ..episode_state import EpisodeRunState


def close_episode(state: EpisodeRunState, runtime: Runtime[EpisodeRuntime]) -> dict[str, Any]:
    """前置条件：`done` 且 `termination` 非空。"""
    assert state.done and state.termination is not None, "close_episode before the episode finished"
    output = EpisodeOutput(
        episode_id=state.episode_id,
        goal_id=state.goal.task_id,
        termination=state.termination,
        judge_reason=state.judge_reason,
        reason=state.reason,
        tasks_used=state.step,
        acts_used=state.total_acts,
        observation=state.ep_ctx.observation,
        memory=state.memory,
    )
    runtime.context.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.EPISODE_END,
            meta={
                "source": "close_episode",
                "episode_id": state.episode_id,
                "task_id": state.episode_id,
                "step": state.ep_ctx.observation.step,
            },
            outcome_episode=output,
        )
    )
    return {"output": output}


__all__ = ["close_episode"]
