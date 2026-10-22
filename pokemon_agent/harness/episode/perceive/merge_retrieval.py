"""保留检索汇合节点；原始物体事件由后续请求直接消费，不折入观测文本。"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from ..episode_runtime import EpisodeRuntime
from ..episode_state import EpisodeRunState


def merge_retrieval(state: EpisodeRunState, runtime: Runtime[EpisodeRuntime]) -> dict[str, Any]:
    """前置：检索已结束；后置：结构化观测与原始事件保持原样。"""
    return {"ep_ctx": state.ep_ctx}
