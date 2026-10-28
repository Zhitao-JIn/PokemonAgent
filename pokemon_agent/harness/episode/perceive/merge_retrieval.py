"""保留检索汇合节点：各检索单元已把结果写进 `ep_ctx`，这里原样交出。"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from ..episode_runtime import EpisodeRuntime
from ..episode_state import EpisodeRunState


def merge_retrieval(state: EpisodeRunState, runtime: Runtime[EpisodeRuntime]) -> dict[str, Any]:
    """前置：检索已结束；后置：结构化观测保持原样。"""
    return {"ep_ctx": state.ep_ctx}
