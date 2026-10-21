"""按本 run 和 L1 goal 身份召回其他局索引，不按目标文本匹配。"""

from __future__ import annotations

import time
from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolRecallReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.memory import EpisodeMemory

from ..episode_runtime import EpisodeRuntime
from ..episode_state import EpisodeRunState


def retrieve_episode_index(
    state: EpisodeRunState, runtime: Runtime[EpisodeRuntime]
) -> dict[str, Any]:
    """返回只更新 episode_index 的 ep_ctx，并始终记一条 read_episode_memory。

    调用方保证 run 与 L1 goal 身份已确定；只召回两者均匹配的其他 episode。
    返回的背景不含本局、不跨 run、不按文字相等关联，只供 index_line 渲染。
    """
    deps = runtime.context
    assert state.run_id and state.goal.task_id, "episode scope requires run and L1 goal identities"
    ep, step = state.episode_id, state.step + 1
    t0 = time.time()
    conditions = {"run_id": state.run_id, "goal_id": state.goal.task_id}
    resp = deps.memory.recall(
        FromHarnessToMemoryToolRecallReq(query="", conditions=conditions, limit=10**6)
    )
    memories = [
        EpisodeMemory(**item.payload, markdown=item.content)
        for item in resp.items
        if item.kind == "episode"
    ]
    episode_index = [memory for memory in memories if memory.episode_id != state.episode_id]
    assert all(
        memory.run_id == state.run_id and memory.goal_id == state.goal.task_id
        for memory in episode_index
    ), "memory recall violated run and goal equality filters"
    t1 = time.time()
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.READ_EPISODE_MEMORY,
            meta={
                "source": "retrieve_episode_index",
                "episode_id": ep,
                "task_id": "",
                "step": step,
            },
            query=f"run_id={state.run_id} goal_id={state.goal.task_id}",
            refs=[m.episode_id for m in episode_index],
            started_at=t0,
            ended_at=t1,
        )
    )
    return {"ep_ctx": state.ep_ctx.model_copy(update={"episode_index": episode_index})}
