"""`dispatch`：选中第一条 `PENDING`、盖 `RUNNING`、拼好这一局的 `EpisodeInput`（纯函数）。"""

from __future__ import annotations

from typing import Any

from pokemon_agent.schemas.harness.domain import EntryStatus, EpisodeInput

from ..run_state import RunState


def dispatch(state: RunState) -> dict[str, Any]:
    """返回 `{"plan", "episode_input", "step"}`。

    前置条件：表里至少一条 `PENDING`（`plan_run` 保证）。
    后置条件：表里恰好一条 `RUNNING`，它的 task 就是 `episode_input.goal`。
    """
    index = next(
        (i for i, entry in enumerate(state.goals) if entry.status is EntryStatus.PENDING), None
    )
    assert index is not None, (
        "dispatch() called with no PENDING goal (plan_run should prevent this)"
    )
    selected = state.goals[index].model_copy(
        update={"status": EntryStatus.RUNNING, "attempts": state.goals[index].attempts + 1}
    )
    episode_input = EpisodeInput(
        run_id=state.run_id,
        episode_id=f"{state.run_id}-ep{state.step + 1}",
        goal=selected.task,
    )
    return {
        "goals": [*state.goals[:index], selected, *state.goals[index + 1 :]],
        "episode_input": episode_input,
        "step": state.step + 1,
    }


__all__ = ["dispatch"]
