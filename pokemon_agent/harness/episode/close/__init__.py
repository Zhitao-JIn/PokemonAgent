"""域⑦ `close`：**收尾链**——主循环结束后的四格，与主循环完全不相交。

只在 `gate/judge` 判 `done` 后进（`episode/episode_graph.py` 的两条条件边）：查 step
记忆 → 查知识 → 校验并蒸馏 → 下结论。**每一条分支都汇到 `close_episode`**——因为
`outcome` 是父子图交界上的输出键，必须由子图自己写出（D2-④，见 `close_episode.py`）。

`close_episode` 是新增的第 21 个节点：v1 想让它留在图外，但子图的输出键不写就是"父侧
保持旧值且不报错"，所以"下结论"必须有自己的格子。
"""

from __future__ import annotations

from .close_episode import close_episode, derive_episode_reason
from .retrieve_verify_knowledge import build_verify_knowledge_query, retrieve_verify_knowledge
from .retrieve_verify_step_memory import retrieve_verify_step_memory
from .verify_and_summarize import verify_and_summarize

__all__ = [
    "build_verify_knowledge_query",
    "close_episode",
    "derive_episode_reason",
    "retrieve_verify_knowledge",
    "retrieve_verify_step_memory",
    "verify_and_summarize",
]
