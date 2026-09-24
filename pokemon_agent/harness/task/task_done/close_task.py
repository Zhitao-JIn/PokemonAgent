"""`close_task`：从终态派生 `TaskOutput`，写 `output`（`task_entry.close` 取走），落 `task_end`。"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind
from pokemon_agent.schemas.harness.domain import TaskOutput

from ..task_runtime import TaskRuntime
from ..task_state import TaskState


def close_task(state: TaskState, runtime: Runtime[TaskRuntime]) -> dict[str, Any]:
    """前置条件：`done` 且 `termination` 非空。"""
    assert state.done and state.termination is not None, "close_task before the task finished"
    output = TaskOutput(
        task_id=state.task.task_id,
        termination=state.termination,
        judge_reason=state.judge_reason,
        reason=state.reason,
        steps_used=state.step,
        memory=state.memory,
    )
    runtime.context.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.TASK_END,
            meta={
                "source": "close_task",
                "episode_id": state.episode_id,
                "task_id": state.task.task_id,
                "step": state.task_ctx.observation.step,
            },
            outcome_task=output,
        )
    )
    return {"output": output}


__all__ = ["close_task"]
