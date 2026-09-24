"""`get_action_space`：把这一键的合法动作边界抄下来（194 从 episode 层挪来——
动作空间是"产键层"的事）。**只改 `task_ctx.action_space` 一处。**

留一条 `get_action_space` 账不是冗余——"这一键允许了哪些动作"是决策的**合法
边界**：事后要解释"为什么它没按某个键"，得先能证明那个键当时不在空间里。

前置条件：`state.task_ctx` 非空（`begin_task` 装配过开局帧）。
后置条件：返回 `{"task_ctx": …}`（补上 action_space）。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import (
    FromHarnessToGameToolGetActionSpaceReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)

from ..task_runtime import TaskRuntime
from ..task_state import TaskState


def get_action_space(state: TaskState, runtime: Runtime[TaskRuntime]) -> dict[str, Any]:
    """把本键的合法动作边界抄进 `task_ctx.action_space`。"""
    deps = runtime.context
    obs = state.task_ctx.observation
    space = deps.game.get_action_space(
        FromHarnessToGameToolGetActionSpaceReq(observation=obs)
    ).action_space
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.GET_ACTION_SPACE,
            meta={
                "source": "get_action_space",
                "episode_id": state.episode_id,
                "task_id": state.task.task_id,
                "step": obs.step,
            },
            names=space.names,
        )
    )
    return {"task_ctx": state.task_ctx.model_copy(update={"action_space": space})}


__all__ = ["get_action_space"]
