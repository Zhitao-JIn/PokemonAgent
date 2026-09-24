"""`perceive` 格（episode 层）：先吸收上一个 task 的结算，再装配感知束 `ep_ctx`。

    absorb_task → sense → 四路检索（本局 TaskMemory / 跨局摘要 / 知识 / 物件）→ merge_retrieval

`absorb_task` 只在上一圈派过 task 时干活（键数、失败连击、结算列表）；`sense` 每圈取一帧（完整档）；
其余单元的增量都是同一个 `ep_ctx` 的逐单元更新。顺序是契约。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from ...compose import compose_units
from ..episode_runtime import EpisodeRuntime
from ..episode_state import EpisodeRunState
from .absorb_task import absorb_task
from .merge_retrieval import merge_retrieval
from .retrieve_global_episode_memory import retrieve_global_episode_memory
from .retrieve_knowledge_semantic_memory import retrieve_knowledge_semantic_memory
from .retrieve_object_semantic_memory import retrieve_object_semantic_memory
from .retrieve_task_memories import retrieve_task_memories
from .sense import sense

_UNITS = (
    absorb_task,
    sense,
    retrieve_task_memories,
    retrieve_global_episode_memory,
    retrieve_knowledge_semantic_memory,
    retrieve_object_semantic_memory,
    merge_retrieval,
)


def perceive(state: EpisodeRunState, runtime: Runtime[EpisodeRuntime]) -> dict[str, Any]:
    """装配这一圈的决策输入（整束进 `ep_ctx`），返回全部增量的合并。

    后置条件：`ep_ctx.observation` 是本圈 `sense` 刚取的帧。
    """
    # ========== 1. 吸收 → 取帧 → 检索 → 合流（顺序是契约；增量全是本层 state 的更新） ==========
    return compose_units(state, runtime, _UNITS)


__all__ = ["perceive"]
