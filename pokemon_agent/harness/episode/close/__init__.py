"""域⑦ `close`：**收尾链**——主循环结束后的四格，与主循环完全不相交。

只在 `gate/judge` 判 `done` 后进（`episode/episode_graph.py` 的两条条件边）：查 step
记忆 → 查知识 → 校验并蒸馏 → 下结论。**每一条分支都汇到 `close_episode`**
——因为 `outcome` 是父子图交界上的输出键，必须由子图自己写出（D2-④，见 `close_episode.py`）。

**这一域里有一对"同一份素材、两个问题"**，产物归属不同、
所以都在记忆里各占一个家族：

| 节点 | 喂进去 | 产物属于谁 | 落哪个家族 |
|---|---|---|---|
| `verify_and_summarize` | 本局可信 step 记忆 | 那一局 | `episode_memory/` |
| `extract_knowledge`（**已摘出图**） | 同一批可信 step 记忆 | 世界 | `knowledge_memory/` |

`close_episode` 是**收尾链的最后一格**：v1 想让它留在图外，但子图的输出键不写就是"父侧
保持旧值且不报错"，所以"下结论"必须有自己的格子。

**`extract_knowledge`（0914 S4）已摘出运行路径**（0914 98）：用户定「knowledge 由人
管理」——它不再出现在 `episode_graph.py` 里，**模块与账都留在原位**（接回去三行，
形状见 `CHANGELOG.md` 第 98 条）。所以本包导出 5 个函数，其中 4 个在图上。
"""

from __future__ import annotations

from .close_episode import close_episode, derive_episode_reason

# 导出它、但图里没有它（0914 98 摘出运行路径）——保留导出是"代码没删"的一部分，
# 接回去时 `episode_graph.py` 的 import 一写就通。
from .extract_knowledge import extract_knowledge
from .retrieve_verify_knowledge import build_verify_knowledge_query, retrieve_verify_knowledge
from .retrieve_verify_step_memory import retrieve_verify_step_memory
from .verify_and_summarize import verify_and_summarize

__all__ = [
    "build_verify_knowledge_query",
    "close_episode",
    "derive_episode_reason",
    "extract_knowledge",
    "retrieve_verify_knowledge",
    "retrieve_verify_step_memory",
    "verify_and_summarize",
]
