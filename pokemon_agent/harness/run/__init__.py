"""run 图（一个 run = 完整一局游戏）——episode 图是它的子图。

步 0 建立本包时只有 `run_state.py`（状态载体）与 `run_graph.py`（装配）；步 2 把
`dispatch` 拆出"接子图"的 `episode` 节点；步 4 把 6 个节点搬成自由函数、`RunHarness`
收成薄类（`harness.py`）、图外侧门落 `run_entry.py`。

**节点平铺在包根**（不像 `episode/` 那样分域目录）：run 图只有 6 格、一眼看得完，
再分一层目录只是多一跳 import（`PLAN_graph_composition.md` §3.1）。因此包根下三种
文件各有各的命名：结构性文件带 `run_` 前缀（`run_graph.py` / `run_state.py` /
`run_entry.py`），节点文件用节点名（`begin.py` / `plan.py` / `dispatch.py` /
`episode.py` / `reflect.py` / `review.py`），外部调用面是 `harness.py`。
"""

from __future__ import annotations

from . import run_entry
from .run_entry import RUN_RECURSION_LIMIT
from .run_graph import compile_run_graph
from .run_state import ResumeEpisode, RunState

__all__ = [
    "RUN_RECURSION_LIMIT",
    "ResumeEpisode",
    "RunState",
    "compile_run_graph",
    "run_entry",
]
