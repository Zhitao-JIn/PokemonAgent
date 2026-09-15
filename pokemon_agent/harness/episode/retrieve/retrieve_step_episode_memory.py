"""`retrieve_step_episode_memory`：查本局单步情景记忆（全量），交给 `decide/think_action`。

**为什么单独查、不折进观测**：跟另外三类（跨局摘要/知识库/语义 object）折进
`observation.facts` 不一样，它是给决策者的一份独立列表——`facts` 是"世界长什么样"的
描述，不该混进"我自己做过什么"。折进 `obs.facts` 的三类里，只有 object 是坐标锚定在
地图上的那种（见 `merge_retrieval`）。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolQueryEpisodeStepsReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)

from ...deps import HarnessDeps
from ..episode_state import EpisodeRunState


def retrieve_step_episode_memory(
    state: EpisodeRunState, runtime: Runtime[HarnessDeps]
) -> dict[str, Any]:
    """查本局全部单步记忆。**只改 `step_episode_memories` 一处。**

    前置条件：`state.observation` 非空（`gate/judge` 之前必有
    `open/record_observation`）。
    后置条件：返回 `{"step_episode_memories": …}`；检索条件与命中清单进一条
    `read_step`（**清单本身就是条数**——`refs` 是数组，长度自己数得出来）。
    这一路**只按 `episode_id` 等值过滤、没有任何打分**——
    `query` 记的就是这个条件本身。
    """
    deps = runtime.context
    assert state.observation is not None, "retrieve_step_episode_memory before judge"
    ep, step = state.episode_id, state.observation.step
    memories = deps.memory.query_episode_steps(
        FromHarnessToMemoryToolQueryEpisodeStepsReq(episode_id=ep)
    ).steps
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.READ_STEP,
            meta={"source": "retrieve_step_episode_memory", "episode_id": ep, "step": step},
            query=f"episode_id={ep}",
            refs=[f"({m.episode_id}, {m.step})" for m in memories],
        )
    )
    return {"step_episode_memories": memories}
