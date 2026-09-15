"""episode 图（一局）——run 图的子图，按 7 个功能域展开的 21 个节点。

步 0 建立本包时只有两件东西：`episode_state.py`（图的状态载体）与 `episode_graph.py`（图的装配）。
步 2 补上 `episode_entry.py`（**图外侧门**：`begin_episode` 装配器与 `run_new` 入口；
原 `prepare_resume` / `run_resume` 已随 checkpoint 恢复链删除）。步 3 起节点按域搬进来
（`open/ gate/ retrieve/ decide/ press/ store/ close/`），形状见
`docs/spec/harness/SPEC.md` 第二、三节。
"""

from __future__ import annotations

from . import episode_entry
from .episode_graph import (
    EpisodeInput,
    EpisodeOutput,
    compile_episode_graph,
)
from .episode_state import EpisodeRunState

__all__ = [
    "EpisodeInput",
    "EpisodeOutput",
    "EpisodeRunState",
    "compile_episode_graph",
    "episode_entry",
]
