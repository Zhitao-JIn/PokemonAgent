"""`task_done` 格（task 层）：**标 → 蒸 → 结**。

    verify_act_memories → summarize_task → close_task

素材是 perceive 装好的 `task_ctx.act_memories`（本格不查库）。没有 ActMemory 时跳过
标与蒸（`reason` 留空、`memory` 为 None），结算照出。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from ...compose import compose_units
from ..task_runtime import TaskRuntime
from ..task_state import TaskState
from .close_task import close_task
from .summarize_task import summarize_task
from .verify_act_memories import verify_act_memories


def task_done(state: TaskState, runtime: Runtime[TaskRuntime]) -> dict[str, Any]:
    """按序跑收尾单元，返回全部增量的合并。"""
    updates: dict[str, Any] = {}
    current = state

    # 步骤 1：有记忆才标、才蒸。
    if current.task_ctx.act_memories:
        inc = compose_units(current, runtime, (verify_act_memories, summarize_task))
        updates.update(inc)
        current = current.model_copy(update=inc)

    # 步骤 2：出结算。
    updates.update(close_task(current, runtime))
    return updates


__all__ = ["task_done"]
