"""run 图的 5 个节点：`begin` / `plan` / `dispatch` / `episode` / `review`。

**`reflect` 已删**（0914 控制台改造）：它的两件事——"收结算进 `outcomes`"与
"按成败弹栈/重试"——全部并入 `review`（那里还要做人的审）。一张图里
"看结果"和"按结果改状态"本来就该挨着，分成两格唯一的效果是多绕一个 superstep。

**这一层目录是"run 下两层"的第一层**：`run/` 包根只留骨架——结构性文件
（`run_graph.py` / `run_state.py` / `run_entry.py`）与外部调用面（`harness.py`），
节点一律下沉到这里，与 `episode/<功能域>/<节点>.py` **同深**。run 只有 5 格，
没有 episode 那种"七个功能域"的切法，所以用一个不分域的
`nodes/` 包裹——**包根清一色是骨架**，读的人不必先分辨某个名字是骨架还是节点。

**节点文件名 = `run_graph.py` 里 `add_node` 的字面量**。

本文件是这一层的统一出口：`run_graph.py` 按名字逐个 import，外部要一次性拿全也走这里。
"""

from __future__ import annotations

from .begin import begin
from .dispatch import active_stack, dispatch, episode_error_handler, project_goals
from .episode import episode, episode_graph
from .plan import plan
from .review import episode_trace_events, review

__all__ = [
    "active_stack",
    "begin",
    "dispatch",
    "episode",
    "episode_error_handler",
    "episode_graph",
    "episode_trace_events",
    "plan",
    "project_goals",
    "review",
]
