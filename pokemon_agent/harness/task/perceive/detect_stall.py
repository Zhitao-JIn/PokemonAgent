"""`detect_stall`：比较"新帧机械状态 + 这一键"与上一键，累计 `stall_count`。
宏动作按结果比：被拒的宏不论参数一律视同同一个无效动作；
其余带上结果那一句（战斗里同一招连出，双方 HP 在变就不算停摆）。

算数与判断分离：阈值（`ACT_STALL_LIMIT`）只由 `review_and_judge` 读。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.brain import Action
from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind
from pokemon_agent.world import MacroOutcome, MacroStatus, TaskObservation

from ..task_runtime import TaskRuntime
from ..task_state import TaskState


def compute_stall(
    after: TaskObservation,
    action: Action,
    prev_key: str | None,
    prev_count: int,
    macro: MacroOutcome | None = None,
) -> tuple[str, int]:
    """纯函数：这一键的停摆键与连续计数（与上一键相同则 +1，否则归 1）。"""
    if macro is None:
        tail = action.describe()
    else:
        tail = "rejected" if macro.status is MacroStatus.REJECTED else macro.describe()
    key = f"{after.stall_key()}|{tail}"
    count = prev_count + 1 if prev_key == key else 1
    return key, count


def detect_stall(state: TaskState, runtime: Runtime[TaskRuntime]) -> dict[str, Any]:
    """没有新帧（首圈）则不写；否则写 `stall_key` / `stall_count` 并记账。"""
    if state.action is None:
        return {}
    assert state.after_observation is not None, "sense 没有产出新帧"
    key, count = compute_stall(
        state.after_observation, state.action, state.stall_key, state.stall_count, state.last_macro
    )
    runtime.context.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.CHECK_STALL,
            meta={
                "source": "detect_stall",
                "episode_id": state.episode_id,
                "task_id": state.task.task_id,
                "step": state.step + 1,
            },
            stall_key=key,
            stall_count=count,
        )
    )
    return {"stall_key": key, "stall_count": count}


__all__ = ["compute_stall", "detect_stall"]
