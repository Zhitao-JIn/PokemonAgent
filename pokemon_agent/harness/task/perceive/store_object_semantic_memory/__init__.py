"""`store_object_semantic_memory`：把这一步涉及的语义记忆（object 交互事件）判定并落库。

**不改状态字段，只落库记账。** 判定规则不在这里——它在本包的 `rules.py`
（`object_fact_events`），本文件只做"取三件套 → 判定 → 逐事件落库与记账"。

本包是七个域里唯一拆成包的：判定层 270 行，塞进节点文件会让"一节点一文件"的体积失衡。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolAppendObjectEventsReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)

from ...task_runtime import TaskRuntime
from ...task_state import TaskState
from .rules import object_fact_events

__all__ = [
    "object_fact_events",
    "store_object_semantic_memory",
]


def store_object_semantic_memory(state: TaskState, runtime: Runtime[TaskRuntime]) -> dict[str, Any]:
    """判定这一步碰到的事件并落库，逐事件记 `write_object_memory`。**不改状态字段，返回空增量。**

    落库前盖 `run_id` 章（落盘签名三元组之一），同 `store_step_episode_memory` 盖
    `episode_id`。

    上一圈没按键（首圈）时不写。
    """
    if state.action is None:
        return {}
    deps = runtime.context
    assert state.after_observation is not None, "sense 没有产出新帧"
    ep, before, action, after = (
        state.episode_id,
        state.task_ctx.observation,
        state.action,
        state.after_observation,
    )

    # 步骤 1：判定（kind 方法表）+ 落库，逐事件记 write_object_memory。
    events = object_fact_events(before, action, after, ep, before.step)
    if events:
        deps.memory.append_object_events(
            FromHarnessToMemoryToolAppendObjectEventsReq(
                events=[e.model_copy(update={"run_id": state.run_id}) for e in events]
            )
        )
    for event in events:
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.WRITE_OBJECT_MEMORY,
                meta={
                    "source": "store_object_semantic_memory",
                    "episode_id": ep,
                    "task_id": state.task.task_id,
                    "step": before.step,
                },
                event=event,
            )
        )
    return {}
