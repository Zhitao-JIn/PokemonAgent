"""episode 图（一局）——run 图的子图，**5 格**（0923 压格）。

`perceive → review_and_judge → plan_episode → act → 回 perceive`，判停走
`episode_done`。**格 = 文件夹，文件 = 最小语义**：五个格各住同名文件夹，
格入口（组合单元的可调用）住文件夹的 `__init__.py`，串接语义见 `compose.py`。
骨架（图装配 / 状态 / 图外侧门 / runtime / 帧槽）留包根。
"""

from __future__ import annotations

from . import episode_entry
from .episode_graph import compile_episode_graph
from .episode_state import EpisodeRunState

__all__ = [
    "EpisodeRunState",
    "compile_episode_graph",
    "episode_entry",
]
