"""episode 图（一局）——run 图的子图，按 7 个功能域展开的 21 个节点。

步 0 建立本包时只有两件东西：`state.py`（图的状态载体）与 `graph.py`（图的装配）。
步 2 补上 `entry.py`（**图外侧门**：`begin_episode` / `prepare_resume` 两个装配器，
以及 `run_new` / `run_resume` 两个入口）。步 3 起节点按域搬进来
（`open/ gate/ retrieve/ decide/ press/ store/ close/`），见
`docs/spec/harness/PLAN_graph_composition.md` §3.1。
"""

from __future__ import annotations

from . import entry
from .graph import (
    NODES_PER_DECISION,
    NODES_PER_PRESS,
    RECURSION_MARGIN,
    compile_episode_graph,
)
from .state import EpisodeRunState

__all__ = [
    "NODES_PER_DECISION",
    "NODES_PER_PRESS",
    "RECURSION_MARGIN",
    "EpisodeRunState",
    "compile_episode_graph",
    "entry",
]
