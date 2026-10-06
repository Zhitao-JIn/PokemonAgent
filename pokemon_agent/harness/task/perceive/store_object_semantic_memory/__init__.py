"""`store_object_semantic_memory`：把这一步的对象交互事件补章后落库。

**不改状态字段，只落库记账。** 判定不在这里（P6 起在 `world/object_events.py`
的 `judge_press`，server 侧）——本文件做"取本步裸事件 → 补三章 → 落库记账"。

**两条路径在这是同一个汇合点**（P6 定案）：

- **按键动作**：`act` 把 `step` 响应的 `event`（单条裸事件）留在 `state.last_event`；
- **脚本动作**：`act` 把终态报告留在 `state.last_report`，`events[]` 批量取出。

两路 dict 同形，统一交 `rules.stamp_events` 补章后 `memorize(kind=object)` 落库。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolMemorizeRecord,
    FromHarnessToMemoryToolMemorizeReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)

from ...task_runtime import TaskRuntime
from ...task_state import TaskState
from .rules import stamp_events

__all__ = [
    "stamp_events",
    "store_object_semantic_memory",
]


def _raw_events(state: TaskState) -> list[dict[str, Any]]:
    """本步的裸事件：脚本动作取报告 `events[]` 批量，按键动作取 step 响应单条。"""
    if state.last_report is not None:
        events = state.last_report.get("events") or []
        return [e for e in events if isinstance(e, dict)]
    if state.last_event is not None:
        return [state.last_event]
    return []


def store_object_semantic_memory(state: TaskState, runtime: Runtime[TaskRuntime]) -> dict[str, Any]:
    """把本步的对象交互事件补章落库，逐事件记 `write_object_memory`。**不改状态字段。**

    落库前盖 `run_id` 章（落盘签名三元组之一），同 `store_step_episode_memory` 盖
    `episode_id`。上一圈没动作（首圈）或两路都没事件（普通移动）时不写。
    """
    if state.action is None:
        return {}
    deps = runtime.context
    assert state.after_observation is not None, "sense 没有产出新帧"
    ep, before = state.episode_id, state.task_ctx.observation

    # 步骤 1：两路汇合 → 补三章。
    events = stamp_events(_raw_events(state), ep, before.step)
    if events:
        deps.memory.memorize(
            FromHarnessToMemoryToolMemorizeReq(
                records=[
                    FromHarnessToMemoryToolMemorizeRecord(
                        kind="object",
                        payload=e.model_copy(update={"run_id": state.run_id}).model_dump(),
                    )
                    for e in events
                ]
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
                    "step": state.step + 1,
                },
                event=event,
            )
        )
    return {}
