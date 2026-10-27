"""`detect_stall`：比较"新帧机械状态 + 这一个动作"与上一个，累计 `stall_count`。
脚本动作按结果比：没执行到位的脚本不论参数一律按"脚本名 + 结局码"算同一个无效动作；
执行到位的带上结果那一句（战斗里同一招连出，双方 HP 在变就不算停摆）。

算数与判断分离：阈值（`loop.act_stall_limit`）只由 `review_and_judge` 读。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.brain import Action
from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind
from pokemon_agent.schemas.memory import ActMemory
from pokemon_agent.world import TaskObservation

from ..task_runtime import TaskRuntime
from ..task_state import TaskState


def compute_stall(
    after: TaskObservation,
    action: Action,
    prev_key: str | None,
    prev_count: int,
    outcome: ActMemory.ScriptOutcome | None = None,
) -> tuple[str, int]:
    """纯函数：这一个动作的停摆键与连续计数（与上一个相同则 +1，否则归 1）。

    outcome：上一动作是脚本时的结构化结局；按键为 None。
    """
    if outcome is None or action.script is None:
        tail = action.describe()
    elif not outcome.ok:
        tail = f"{action.script.name} → {outcome.code}"
    else:
        detail = outcome.summary or outcome.reason
        tail = f"{action.script.name} → {outcome.code}"
        if detail:
            tail += f"：{detail}"
    key = f"{after.stall_key()}|{tail}"
    count = prev_count + 1 if prev_key == key else 1
    return key, count


def detect_stall(state: TaskState, runtime: Runtime[TaskRuntime]) -> dict[str, Any]:
    """没有新帧（首圈）则不写；否则写 `stall_key` / `stall_count` 并记账。"""
    if state.action is None:
        return {}
    assert state.after_observation is not None, "sense 没有产出新帧"
    key, count = compute_stall(
        state.after_observation,
        state.action,
        state.stall_key,
        state.stall_count,
        state.last_outcome,
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
