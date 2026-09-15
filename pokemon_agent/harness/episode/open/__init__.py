"""域① `open`：一条决策的**开场两连**（存上一环 → 记这一环的输入）。

**每决策一次，不是每键一次**——这两个节点既不判也不改 state，所以它们不是
"决策的一部分"，而是决策之前的两笔记账。

名字取"一条决策的开场"（D10：原拟 `boundary/`，改 `open/`）；它与整局收尾的
`close/` **不在同一层级**：`close/` 是一局一次，`open/` 是每决策一次。
"""

from __future__ import annotations

from .record_observation import record_observation
from .save_checkpoint import save_checkpoint

__all__ = [
    "record_observation",
    "save_checkpoint",
]
