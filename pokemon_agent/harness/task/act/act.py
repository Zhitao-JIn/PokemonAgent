"""`act`：执行 `plan_task` 产出的那**一个键或一个宏**，推进世界，决策数 +1。**只有它推进世界。**

`settle=True` 恒定：每键之后都要判停与决策，那一帧必须等世界走完。宏由 world 执行到底，
结果落 `last_macro` 给下一轮决策与记忆。
感知新帧、停摆与 ActMemory 都在下一圈的 `perceive`；`action` 留在 state 上给它消费。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import (
    FromHarnessToGameToolExecuteReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)

from ..task_runtime import TaskRuntime
from ..task_state import TaskState


def act(state: TaskState, runtime: Runtime[TaskRuntime]) -> dict[str, Any]:
    """执行 `state.action`（一个键或一个宏），`step+1`。`action` 留给下一圈 perceive 消费。

    前置条件：`state.action` 非空（`plan_task` 写的）。
    后置条件：宏时 `last_macro` 是它的结果，按键时为 None。
    """
    deps = runtime.context
    assert state.action is not None, "act before plan_task"
    before = state.task_ctx.observation

    # 步骤 1：按 `before` 这份观测执行（settle 恒 True：每键都是决策尾）。
    resp = deps.game.execute(
        FromHarnessToGameToolExecuteReq(action=state.action, observation=before, settle=True)
    )

    # 步骤 2：记 press_key / run_macro，决策数 +1。
    meta = {
        "source": "act",
        "episode_id": state.episode_id,
        "task_id": state.task.task_id,
        "step": before.step,
    }
    if resp.outcome is not None:
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(kind=TraceKind.RUN_MACRO, meta=meta, macro=resp.outcome)
        )
    else:
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.PRESS_KEY, meta=meta, action=state.action
            )
        )
    return {"step": state.step + 1, "last_macro": resp.outcome}


__all__ = ["act"]
