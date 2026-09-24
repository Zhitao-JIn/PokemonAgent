"""`absorb_episode`：吸收上一圈 `act` 交回的 `EpisodeOutput`——收进 `episode_outputs`、更新失败连击。

首圈（`pending_episode` 为 None）不写。与 episode 层 `absorb_task` 同一个位置：
吸收在 perceive，判定在 review_and_judge。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from ..run_state import RunState
from ..runtime import RunRuntime


def absorb_episode(state: RunState, runtime: Runtime[RunRuntime]) -> dict[str, Any]:
    """把 `pending_episode` 折进 state，并清掉它。"""
    out = state.pending_episode
    if out is None:
        return {}
    return {
        "episode_outputs": [*state.episode_outputs, out],
        "fail_streak": 0 if out.success else state.fail_streak + 1,
        "pending_episode": None,
    }


__all__ = ["absorb_episode"]
