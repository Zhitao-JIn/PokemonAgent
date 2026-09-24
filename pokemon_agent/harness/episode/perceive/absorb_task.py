"""`absorb_task`：吸收上一圈 `act` 交回的 `TaskOutput`——键数、失败连击、结算列表。

**不收帧**：这一圈的当前帧由紧随其后的 `sense` 自己取（完整档）。

**不定案**：盖章、人审、放弃剩余条目都在 `review_and_judge`——那里才知道最终定案
（人可能推翻）。这里的失败连击按机器结算先记，推翻时由 review 修正。

首圈（`pending_task` 为 None）不写。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness.domain import TaskOutput, Termination

from ..episode_runtime import EpisodeRuntime
from ..episode_state import EpisodeRunState


def absorb_task(state: EpisodeRunState, runtime: Runtime[EpisodeRuntime]) -> dict[str, Any]:
    """把 `pending_task` 折进 state，并清掉它。"""
    out = state.pending_task
    if out is None:
        return {}
    return {
        "total_acts": state.total_acts + out.steps_used,
        "fail_streak": _fail_streak(state.fail_streak, out),
        "task_outputs": [*state.task_outputs, out],
        "pending_task": None,
    }


def _fail_streak(streak: int, out: TaskOutput) -> int:
    """成了清零；被打断（`INTERRUPTED`）不算失败、原样保留；其余 +1。"""
    if out.success:
        return 0
    if out.termination is Termination.INTERRUPTED:
        return streak
    return streak + 1


__all__ = ["absorb_task"]
