"""域③ `retrieve`：四路检索 + 汇聚。

这五个节点在图上是一条直线且**彼此无数据依赖**（都只读 `observation`），
`merge_retrieval` 是它们的汇聚点。四路各写各的 state 字段，只有
`merge_retrieval` 会改 `observation`（把 object 那一类折进 `obs.facts`）。
边上的先后是图引擎的要求，不是因果依赖。
"""

from __future__ import annotations

from .merge_retrieval import merge_retrieval
from .retrieve_global_episode_memory import retrieve_global_episode_memory
from .retrieve_knowledge_semantic_memory import (
    build_knowledge_query,
    retrieve_knowledge_semantic_memory,
)
from .retrieve_object_semantic_memory import retrieve_object_semantic_memory
from .retrieve_step_episode_memory import retrieve_step_episode_memory

__all__ = [
    "build_knowledge_query",
    "merge_retrieval",
    "retrieve_global_episode_memory",
    "retrieve_knowledge_semantic_memory",
    "retrieve_object_semantic_memory",
    "retrieve_step_episode_memory",
]
