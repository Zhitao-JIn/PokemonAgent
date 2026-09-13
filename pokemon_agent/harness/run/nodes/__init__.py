"""run 图的 6 个节点：`begin` / `plan` / `dispatch` / `episode` / `reflect` / `review`。

**这一层目录是"run 下两层"的第一层**：`run/` 包根只留骨架——结构性文件
（`run_graph.py` / `run_state.py` / `run_entry.py`）与外部调用面（`harness.py`），
节点一律下沉到这里，与 `episode/<功能域>/<节点>.py` **同深**（`PLAN_graph_composition.md`
§3.1 v16）。run 只有 6 格，没有 episode 那种"七个功能域"的切法，所以用一个不分域的
`nodes/` 包裹——**包根清一色是骨架**，读的人不必先分辨某个名字是骨架还是节点。

**节点文件名 = `run_graph.py` 里 `add_node` 的字面量**（§5.3-⑤）；
`scripts/check_graph_phases.py` 靠 `ast` 抽这两头做机械核对。

本文件是这一层的统一出口：`run_graph.py` 按名字逐个 import，外部要一次性拿全也走这里。
"""

from __future__ import annotations

from .begin import begin
from .dispatch import dispatch, episode_error_handler, project_goals
from .episode import episode, episode_graph
from .plan import (
    RUN_TRACE_MASK,
    apply_goals_edit,
    ask_planner_with_retry,
    plan,
    to_tasks,
)
from .reflect import goal_retries_exhausted, reflect
from .review import episode_trace_events, review

__all__ = [
    "RUN_TRACE_MASK",
    "apply_goals_edit",
    "ask_planner_with_retry",
    "begin",
    "dispatch",
    "episode",
    "episode_error_handler",
    "episode_graph",
    "episode_trace_events",
    "goal_retries_exhausted",
    "plan",
    "project_goals",
    "reflect",
    "review",
    "to_tasks",
]
