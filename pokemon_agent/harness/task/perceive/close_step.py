"""`close_step`：把本圈新帧**转正**进 `task_ctx.observation`；上一圈按过键时再记 `advance_step`。

必须排在两个 store 之后：它们要 before（`task_ctx.observation`）与 after（`after_observation`）
同时在场。首圈没有 before，新帧直接转正成这个 task 的开局帧。键数 `step` 由 `act` 加，这里不碰。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind

from ..task_runtime import TaskRuntime
from ..task_state import TaskState


def close_step(state: TaskState, runtime: Runtime[TaskRuntime]) -> dict[str, Any]:
    """转正新帧、清两个流转字段；上一圈按过键才记 `ADVANCE_STEP`。"""
    after = state.after_observation
    assert after is not None, "close_step 之前 sense 必须已取帧"
    if state.action is not None:
        runtime.context.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.ADVANCE_STEP,
                meta={
                    "source": "close_step",
                    "episode_id": state.episode_id,
                    "task_id": state.task.task_id,
                    "step": after.step,
                },
                next_step=after.step,
            )
        )
    return {
        "task_ctx": state.task_ctx.model_copy(update={"observation": after}),
        "after_observation": None,
        "action": None,
    }


__all__ = ["close_step"]
