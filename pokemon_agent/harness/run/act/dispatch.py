"""`dispatch`：选中第一条 `PENDING`、盖 `RUNNING`、拼好这一局的 `EpisodeInput`（纯函数）。"""

from __future__ import annotations

from typing import Any

from pokemon_agent.schemas.harness.domain import EntryStatus, EpisodeInput

from ...planning import dispatch_index
from ..run_state import RunState


def dispatch(state: RunState) -> dict[str, Any]:
    """返回 `{"plan", "episode_input", "step"}`。

    前置条件：表里至少一条 `PENDING`（`plan_run` 保证）。
    后置条件：表里恰好一条 `RUNNING`，它的 task 就是 `episode_input.goal`；
    `episode_input.tasks` 是这一条目的 `frozen_tasks` 副本（冻结开关关着时由 episode 层忽略）。
    """
    index = dispatch_index(state.goals, state.execution_order)
    selected = state.goals[index].model_copy(
        update={"status": EntryStatus.RUNNING, "attempts": state.goals[index].attempts + 1}
    )
    episode_input = EpisodeInput(
        run_id=state.run_id,
        run_goal=state.run_goal.goal,
        episode_id=f"{state.run_id}-ep{state.step + 1}",
        goal=selected.task,
        tasks=list(selected.frozen_tasks),
    )
    return {
        "goals": [*state.goals[:index], selected, *state.goals[index + 1 :]],
        "episode_input": episode_input,
        "step": state.step + 1,
    }


__all__ = ["dispatch"]
