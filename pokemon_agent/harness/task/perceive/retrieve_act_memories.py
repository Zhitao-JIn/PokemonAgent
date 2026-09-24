"""`retrieve_act_memories`（task 层）：查本 task 的全部 ActMemory → `task_ctx.act_memories`。

task 只读**直属下一级**的记忆（本 task 按过的键）：决策取最近几条、判定取最近几条、
收尾的标记与蒸馏取全部。排在两个 store 之后，所以上一键刚写的那条也在里面。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolQueryActMemoriesReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)

from ..task_runtime import TaskRuntime
from ..task_state import TaskState


def retrieve_act_memories(state: TaskState, runtime: Runtime[TaskRuntime]) -> dict[str, Any]:
    """按 `task_id` 章筛出本 task 的 ActMemory，写 `task_ctx.act_memories`。

    记一条 `read_act_memory`。
    """
    deps = runtime.context
    ep, task_id = state.episode_id, state.task.task_id
    acts = deps.memory.query_act_memories(
        FromHarnessToMemoryToolQueryActMemoriesReq(episode_id=ep)
    ).entries
    mine = [a for a in acts if a.task_id == task_id]
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.READ_ACT_MEMORY,
            meta={
                "source": "retrieve_act_memories",
                "episode_id": ep,
                "task_id": task_id,
                "step": state.start_step + state.step,
            },
            query=f"episode_id={ep} task_id={task_id}",
            refs=[f"({m.episode_id}, {m.step})" for m in mine],
        )
    )
    return {"task_ctx": state.task_ctx.model_copy(update={"act_memories": mine})}


__all__ = ["retrieve_act_memories"]
