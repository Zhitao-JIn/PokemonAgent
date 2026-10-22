"""`dispatch_task`：选中任务表第一条 `PENDING`、盖 `RUNNING`、拼好 `TaskInput`（纯函数）。"""

from __future__ import annotations

from typing import Any

from pokemon_agent.schemas.harness.domain import EntryStatus, TaskInput
from pokemon_agent.schemas.memory import TaskMemory

from ...planning import dispatch_index
from ..episode_state import EpisodeRunState, current_knowledge


def _task_index(state: EpisodeRunState, goal: str, task_id: str) -> list[TaskMemory]:
    """同局同目标的此前 task 按 total_acts 升序；调用方保证其中不含当前 task。"""
    memories = sorted(
        (
            memory
            for memory in state.ep_ctx.task_memories
            if memory.goal == goal and memory.episode_id == state.episode_id
        ),
        key=lambda memory: memory.total_acts,
    )
    index = [
        memory.model_copy(update={"first_frame": None, "last_frame": None}) for memory in memories
    ]
    assert all(memory.task_id != task_id for memory in index), "task index includes current task"
    return index


def dispatch_task(state: EpisodeRunState) -> dict[str, Any]:
    """返回 `{"tasks", "step", "task_input"}`。

    `tasks` / `step` 是 `act` 要写回状态的两项，`task_input` 交给 `run_task`。

    前置条件：任务表里至少一条 `PENDING`（`plan_episode` 保证）。
    后置条件：表里被选中的那条变为 `RUNNING`，它的 task 就是 `task_input.task`；`step` 比入参多 1。
    """
    index = dispatch_index(state.tasks, state.execution_order)
    entry = state.tasks[index]

    # 步骤 1：标 RUNNING，装配 TaskInput（快照 = 本局累计键数，task 内恒定）。
    task_id = f"{state.episode_id}-task{state.step + 1}"
    running = entry.model_copy(
        update={
            "status": EntryStatus.RUNNING,
            "attempts": entry.attempts + 1,
            "last_task_id": task_id,
        }
    )
    task_input = TaskInput(
        run_id=state.run_id,
        episode_id=state.episode_id,
        entry_id=entry.entry_id,
        task=entry.task.model_copy(update={"task_id": task_id}),
        total_acts=state.total_acts,
        knowledge=current_knowledge(state),
        task_index=_task_index(state, entry.task.goal, task_id),
        actions_budget=(
            None
            if state.actions_budget is None
            else max(0, state.actions_budget - state.total_acts)
        ),
        remaining_s=state.remaining_s,
    )
    tasks = [*state.tasks[:index], running, *state.tasks[index + 1 :]]
    assert tasks[index].entry_id == task_input.entry_id
    return {"tasks": tasks, "step": state.step + 1, "task_input": task_input}


__all__ = ["dispatch_task"]
