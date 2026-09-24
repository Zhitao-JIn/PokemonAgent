"""`retrieve_task_memories`（episode 层）：查本局全部 TaskMemory → `ep_ctx.task_memories`。

episode 只读**直属下一级**的记忆：判定、拆解、收尾的蒸馏都用这一份（按 `start_step` 升序）。
不读 ActMemory——按键层的细节由 task 层自己消化进 TaskMemory。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolQueryTaskMemoriesReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)

from ..episode_runtime import EpisodeRuntime
from ..episode_state import EpisodeRunState


def retrieve_task_memories(
    state: EpisodeRunState, runtime: Runtime[EpisodeRuntime]
) -> dict[str, Any]:
    """查本局全部 TaskMemory，写 `ep_ctx.task_memories`，记一条 `read_task_memory`。"""
    deps = runtime.context
    ep, step = state.episode_id, state.total_acts
    memories = deps.memory.query_task_memories(
        FromHarnessToMemoryToolQueryTaskMemoriesReq(episode_id=ep)
    ).memories
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.READ_TASK_MEMORY,
            meta={
                "source": "retrieve_task_memories",
                "episode_id": ep,
                "task_id": ep,
                "step": step,
            },
            query=f"episode_id={ep}",
            refs=[f"({m.episode_id}, {m.task_id})" for m in memories],
        )
    )
    return {"ep_ctx": state.ep_ctx.model_copy(update={"task_memories": memories})}


__all__ = ["retrieve_task_memories"]
