"""`act`：执行 `plan_task` 产出的那**一个键或一条脚本**，推进世界，决策数 +1。
**只有它推进世界。**

`settle=True` 恒定（键）：每键之后都要判停与决策，那一帧必须等世界走完。脚本由
world 执行到底，终态报告落 `last_report`、一行结果落 `last_result` 给下一轮决策与记忆。
脚本一次调用占 harness 账一步（内部 N 键不展开，P5 定案）。
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

from ..script_report import describe_call
from ..task_runtime import TaskRuntime
from ..task_state import TaskState


def act(state: TaskState, runtime: Runtime[TaskRuntime]) -> dict[str, Any]:
    """执行 `state.action`（一个键或一条脚本），`step+1`。

    `action` 留给下一圈 perceive 消费。
    前置条件：`state.action` 非空（`plan_task` 写的）。
    后置条件：脚本时 `last_report` 是终态报告、`last_result` 是一行结果；按键时为 None / 空串。
    """
    deps = runtime.context
    assert state.action is not None, "act before plan_task"
    before = state.task_ctx.observation

    # 步骤 1：按 `before` 这份观测执行（settle 恒 True：每键都是决策尾）。
    resp = deps.game.execute(
        FromHarnessToGameToolExecuteReq(action=state.action, observation=before, settle=True)
    )

    # 步骤 2：记 act_call（key/script 两形），决策数 +1。
    # 账面步号 = 圈号（state.step 尚未自增，+1 即本圈帧号，0928 定稿）。
    meta = {
        "source": "act",
        "episode_id": state.episode_id,
        "task_id": state.task.task_id,
        "step": state.step + 1,
    }
    if state.action.script is not None:
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.ACT_CALL, meta=meta, action=state.action, report=resp.report
            )
        )
        return {
            "step": state.step + 1,
            "last_report": resp.report,
            "last_result": describe_call(state.action, resp.report or {}),
            "last_event": None,  # 脚本的事件在 report.events[] 里
        }
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(kind=TraceKind.ACT_CALL, meta=meta, action=state.action)
    )
    return {
        "step": state.step + 1,
        "last_event": resp.event,  # P6：world 侧判定的本键裸事件（可为 None）
        "last_report": None,
        "last_result": "",
    }


__all__ = ["act"]
