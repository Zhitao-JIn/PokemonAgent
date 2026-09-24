"""`plan_episode` 格：**任务链的产出点**——队列空时问 decomposer 把本局目标拆成一串 task。

单文件格：单元就是 `plan_episode.py`。
"""

from __future__ import annotations

from .plan_episode import plan_episode

__all__ = ["plan_episode"]
