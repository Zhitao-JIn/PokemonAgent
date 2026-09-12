"""`merge_retrieval`：把四路检索的结果**汇到一处**——只有 object 那一路会改状态，
其余三路只是在这里合进一条 `MEMORY_READ` 账。

**只有 `known_objects` 折进 `obs.facts`**：它虽然也是跨步骤攒出来的，但坐标锚定在
这张地图上，跟 `walk_map`/`landmarks` 同一个可信度级别。`knowledge`（知识库）与
`global_episode_memories`（跨局摘要）各走各的 `FromHarnessToBrainToolChooseOnceReq`
字段，在 `decide_action.md` 里各有独立占位符和可信度说明，**不混进"已知事实"**。
本局单步（`step_episode_memories`）本来就没折进观测，仍是独立列表。

**四路读、一条账**：四类检索拆到四个节点查，但事件仍共用一条 `MEMORY_READ`——拆成
多条会让人以为它们发生在循环的不同位置（见 `tools/trace/render.py::memory_read`）。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq
from pokemon_agent.trace import TraceKind

from ...deps import HarnessDeps
from ..episode_state import EpisodeRunState


def merge_retrieval(
    state: EpisodeRunState, runtime: Runtime[HarnessDeps]
) -> dict[str, Any]:
    """把语义 object 折进这一帧观测，并记一条 `MEMORY_READ`。**只改 `observation` 一处，不查库。**

    前置条件：四路 retrieve 都已跑过（`state` 里四个字段齐备）、`state.observation` 非空。
    后置条件：返回 `{"observation": …}`；`knowledge`/`episode_memories` 原样留在 state 里
    给 `decide/think_action` 自己取。
    """
    deps = runtime.context
    assert state.observation is not None, "merge_retrieval before judge"
    obs, ep, step = state.observation, state.episode_id, state.observation.step

    # 步骤 1：折进语义记忆（object）——坐标锚定，跟 walk_map/landmarks 同一可信度级别。
    if state.object_semantic_memory:
        obs = obs.model_copy(
            update={"facts": {**obs.facts, "known_objects": state.object_semantic_memory}}
        )

    # 步骤 2：知识库/跨局摘要不再折进 obs.facts——只在这里算出文本，供本步
    # MEMORY_READ 记账用；真正喂给 think_action 的路径是 state 里那两个字段
    # 原样传下去，由 think_action 自己拼 FromHarnessToBrainToolChooseOnceReq。
    knowledge_text = (
        "\n\n".join(state.knowledge_semantic_memory.contents)
        if state.knowledge_semantic_memory
        else ""
    )

    # 步骤 3：连同 step_episode_memories，写一条 MEMORY_READ。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.MEMORY_READ,
            episode_id=ep,
            step=step,
            memories=state.step_episode_memories,
            known_objects=state.object_semantic_memory,
            knowledge=knowledge_text,
            episode_memories=state.global_episode_memories,
            knowledge_sources=(
                state.knowledge_semantic_memory.sources
                if state.knowledge_semantic_memory
                else []
            ),
        )
    )
    return {"observation": obs}
