"""`dispatch_task`：选中任务表第一条 `PENDING`、盖 `RUNNING`、拼好 `TaskInput`（纯函数）。"""

from __future__ import annotations

from typing import Any

from pokemon_agent.schemas.harness.domain import EntryStatus, TaskInput

from ..episode_state import EpisodeRunState, current_knowledge


def dispatch_task(state: EpisodeRunState) -> dict[str, Any]:
    """返回 `{"tasks", "step", "task_input"}`。

    `tasks` / `step` 是 `act` 要写回状态的两项，`task_input` 交给 `run_task`。

    前置条件：任务表里至少一条 `PENDING`（`plan_episode` 保证）。
    后置条件：表里被选中的那条变为 `RUNNING`，它的 task 就是 `task_input.task`；`step` 比入参多 1。
    """
    index = next(
        (i for i, entry in enumerate(state.tasks) if entry.status is EntryStatus.PENDING), None
    )
    assert index is not None, (
        "dispatch_task() without a PENDING task (plan_episode should prevent this)"
    )
    entry = state.tasks[index]

    # 步骤 1：标 RUNNING，装配 TaskInput（键号基数 = 本局累计键数）。
    running = entry.model_copy(update={"status": EntryStatus.RUNNING})
    task_input = TaskInput(
        run_id=state.run_id,
        episode_id=state.episode_id,
        task=entry.task,
        start_step=state.total_acts,
        knowledge=current_knowledge(state),
    )
    tasks = [*state.tasks[:index], running, *state.tasks[index + 1 :]]
    assert tasks[index].task == task_input.task
    return {"tasks": tasks, "step": state.step + 1, "task_input": task_input}


__all__ = ["dispatch_task"]
