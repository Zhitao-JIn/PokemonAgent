"""`detect_stall`：比较"新帧机械状态 + 这一键"与上一键，累计 `stall_count`。

算数与判断分离：阈值（`STALL_LIMIT`）只由 `review_and_judge` 读。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.brain import Action
from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind
from pokemon_agent.world import Observation

from ..task_runtime import TaskRuntime
from ..task_state import TaskState


def compute_stall(
    after: Observation, action: Action, prev_key: str | None, prev_count: int
) -> tuple[str, int]:
    """纯函数：这一键的停摆键与连续计数（与上一键相同则 +1，否则归 1）。"""
    key = f"{after.stall_key()}|{action.describe()}"
    count = prev_count + 1 if prev_key == key else 1
    return key, count


def detect_stall(state: TaskState, runtime: Runtime[TaskRuntime]) -> dict[str, Any]:
    """没有新帧（首圈）则不写；否则写 `stall_key` / `stall_count` 并记账。"""
    if state.action is None:
        return {}
    assert state.after_observation is not None, "sense 没有产出新帧"
    key, count = compute_stall(
        state.after_observation, state.action, state.stall_key, state.stall_count
    )
    runtime.context.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.CHECK_STALL,
            meta={
                "source": "detect_stall",
                "episode_id": state.episode_id,
                "task_id": state.task.task_id,
                "step": state.task_ctx.observation.step,
            },
            stall_key=key,
            stall_count=count,
        )
    )
    return {"stall_key": key, "stall_count": count}


__all__ = ["compute_stall", "detect_stall"]
