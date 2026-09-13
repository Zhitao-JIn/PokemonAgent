"""`retrieve_global_episode_memory` 与它的场景键 `build_scene_key`。

跨局摘要记忆按"场景 + 任务目标"检索：场景键由 `build_scene_key` 从这一帧观测拼出，
`None`（没有 `place`，即场景未知）时**直接返回空列表，不是异常**——那是一局刚开始、
地形还没读出来的正常情形。

`build_scene_key` 跟着本节点（判据："删掉它唯一的调用者之后还有没有人要？"——
没有，见 `PLAN_graph_composition.md` §3.5）。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.config import EPISODE_MEMORY_RECALL_LIMIT
from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolQueryEpisodeSummariesReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.world import Observation

from ...deps import HarnessDeps
from ..episode_state import EpisodeRunState


def build_scene_key(obs: Observation) -> str | None:
    """拼跨局摘要检索用的场景键；`obs.place` 为 None 时没有场景可过滤，返回 None。"""
    if obs.place is None:
        return None
    return "|".join(
        filter(
            None,
            (
                f"map:{obs.place.map_id}",
                f"scene:{obs.facts.scene_value}",
                f"overlay:{obs.facts.overlay_value}",
            ),
        )
    )


def retrieve_global_episode_memory(
    state: EpisodeRunState, runtime: Runtime[HarnessDeps]
) -> dict[str, Any]:
    """查跨局摘要记忆（按场景 + 任务目标）。**只改 `global_episode_memories` 一处。**

    检索面限本 run（`run_id`）：跨 run 的摘要不互相喂——取舍见 `CHANGELOG.md`
    2026-09-03 条目。

    前置条件：`state.observation` 非空。
    后置条件：返回 `{"global_episode_memories": …}`；场景未知时为空列表，
    两种情况都记一条 `RETRIEVE_NODE`（记 `count=0` 与"没查"是两回事）。
    """
    deps = runtime.context
    assert state.observation is not None, "retrieve_global_episode_memory before judge"
    obs, ep, step = state.observation, state.episode_id, state.observation.step
    scene_key = build_scene_key(obs)
    if scene_key is None:
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.RETRIEVE_NODE,
                episode_id=ep,
                step=step,
                read_kind="global",
                count=0,
                refs="",
            )
        )
        return {"global_episode_memories": []}
    episode_memories = deps.memory.query_episode_summaries(
        FromHarnessToMemoryToolQueryEpisodeSummariesReq(
            scene=scene_key,
            query=state.task.goal,
            limit=EPISODE_MEMORY_RECALL_LIMIT,
            run_id=deps.run_id,
        )
    ).summaries
    refs = " ".join(m.episode_id for m in episode_memories)
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.RETRIEVE_NODE,
            episode_id=ep,
            step=step,
            read_kind="global",
            count=len(episode_memories),
            refs=refs,
        )
    )
    return {"global_episode_memories": episode_memories}
