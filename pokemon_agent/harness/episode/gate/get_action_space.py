"""`get_action_space`：按这一帧观测算这一步能用的动作空间。

**只在没终止的分支上跑**（`judge` 出口的 `done=False` 那条边），只改 `action_space`
一处。它是"闸口"的第二半：`judge` 决定要不要继续，它给出"继续的话能按什么"。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import (
    FromHarnessToGameToolGetActionSpaceReq,
    FromHarnessToTraceToolAppendReq,
)
from pokemon_agent.trace import TraceKind

from ...deps import HarnessDeps
from ..episode_state import EpisodeRunState


def get_action_space(
    state: EpisodeRunState, runtime: Runtime[HarnessDeps]
) -> dict[str, Any]:
    """把这一步的合法动作边界抄下来。**只改 `action_space` 一处。**

    留一条 `ACTION_SPACE` 账不是冗余——"这一步允许了哪些动作"是大脑决策的**合法
    边界**：事后要解释"为什么它没按某个键"，得先能证明那个键当时不在空间里。

    前置条件：`state.observation` 非空（`judge` 之前必有 `record_observation`）。
    后置条件：返回 `{"action_space": …}`。
    """
    deps = runtime.context
    assert state.observation is not None, "get_action_space before judge"
    space = deps.game.get_action_space(
        FromHarnessToGameToolGetActionSpaceReq(observation=state.observation)
    ).action_space
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.ACTION_SPACE,
            episode_id=state.episode_id,
            step=state.observation.step,
            names=space.names,
        )
    )
    return {"action_space": space}
