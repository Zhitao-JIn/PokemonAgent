"""按 run_goal 等值召回其他局的一行背景索引，不把本局混入背景。"""

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

    run_goal 非空时按等值条件全取其他 episode；空串不查库，索引为空。
    调用方保证运行身份已确定；返回的背景不含本局，只供 index_line 渲染。
    """
    deps = runtime.context
    ep, step = state.episode_id, state.step + 1
    t0 = time.time()
    episode_index: list[EpisodeMemory] = []
    if state.run_goal:
        resp = deps.memory.recall(
            FromHarnessToMemoryToolRecallReq(
                query="", conditions={"run_goal": state.run_goal}, limit=10**6
            )
        )
        memories = [
            EpisodeMemory(**item.payload, markdown=item.content)
            for item in resp.items
            if item.kind == "episode"
        ]
        episode_index = [m for m in memories if m.episode_id != state.episode_id]
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
            query=f"run_goal={state.run_goal}",
            refs=[m.episode_id for m in episode_index],
            started_at=t0,
            ended_at=t1,
        )
    )
    return {"ep_ctx": state.ep_ctx.model_copy(update={"episode_index": episode_index})}
