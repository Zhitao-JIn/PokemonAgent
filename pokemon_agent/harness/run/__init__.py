"""run 图（一个 run = 完整一局游戏）——episode 图是它的子图。

步 0 建立本包时只有 `state.py`（图的状态载体）与 `graph.py`（图的装配）。
步 2 把 `dispatch` 换成内置子图节点，步 4 把 5 个节点搬成自由函数、`RunHarness`
收成薄类（`harness.py`），见 `docs/spec/harness/PLAN_graph_composition.md` §6。
"""

from __future__ import annotations

from .graph import compile_run_graph
from .state import ResumeEpisode, RunState

__all__ = ["ResumeEpisode", "RunState", "compile_run_graph"]
