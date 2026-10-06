"""`retrieve_act_memories`（task 层）：查本 task 的全部 ActMemory → `task_ctx.act_memories`。

task 只读**直属下一级**的记忆（本 task 按过的键）：决策取最近几条、判定取最近几条、
收尾的标记与蒸馏取全部。排在两个 store 之后，所以上一键刚写的那条也在里面。
"""

from __future__ import annotations

import time
from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolRecallReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.memory import ActMemory

from ..task_runtime import TaskRuntime
from ..task_state import TaskState


def retrieve_act_memories(state: TaskState, runtime: Runtime[TaskRuntime]) -> dict[str, Any]:
    """取这一局的 ActMemory，按 `task_id` 章筛出本 task 的，写 `task_ctx.act_memories`。

    记一条 `read_act_memory`（`refs` 是读口交回的整局条目）；双时刻定案
    （2026-09-27）：检索操作前后取时，进封套做排序与延迟统计的依据。
    """
    deps = runtime.context
    ep, task_id = state.episode_id, state.task.task_id
    t0 = time.time()
    resp = deps.memory.recall(
        FromHarnessToMemoryToolRecallReq(query="", conditions={"episode_id": ep}, limit=10**6)
    )
    entries = [ActMemory.model_validate(item.payload) for item in resp.items if item.kind == "act"]
    t1 = time.time()
    mine = [m for m in entries if m.task_id == task_id]
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.READ_ACT_MEMORY,
            meta={
                "source": "retrieve_act_memories",
                "episode_id": ep,
                "task_id": task_id,
                "step": state.step + 1,
            },
            query=f"episode_id={ep}",
            refs=[f"({m.episode_id}, {m.step})" for m in entries],
            started_at=t0,
            ended_at=t1,
        )
    )
    return {"task_ctx": state.task_ctx.model_copy(update={"act_memories": mine})}


__all__ = ["retrieve_act_memories"]
