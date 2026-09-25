"""harness 包：控制循环本体（LangGraph 状态图），全项目唯一写 trace 的地方。

**三张同构的图**，每张 5–6 格：`perceive → review_and_judge → plan_* → act → 回 perceive`，
判停走 `*_done`。上层的 `act` 经下层的图外入口调下层子图（形态 B）：

- `run/`：一圈 = 一局。目标表驱动；`run_entry.new_run` 是图外入口，`RunHarness` 是外部调用面。
- `episode/`：一圈 = 一个 task。decomposer 拆任务链；`episode_entry.run_episode` 是图外入口。
- `task/`：一圈 = 一个键。chooser 每键出一个键；`task_entry.run_task` 是图外入口。
- 共享件：`compose.py`（格内单元串接）、`judging.py`（机械三类 + 问 judger 记账）、
  `sensing.py`（取一帧）、`reviewing.py`（问人并记账）。
- `checkpoint/`：两级存档、恢复与回放（`docs/spec/checkpoint/SPEC.md`）。
- `run/runtime.py` / `episode/episode_runtime.py` / `task/task_runtime.py`：三级 context，
  上级嵌套持有下级；`trace` / `memory` / `reviewer` 同一实例跨级共享。
- `interface/`：harness 真正需要外面给的东西——`Reviewer`（插话 + 审）与
  plan 那一版的产出模型（`PlannerOutcome` / `GoalUpdate`）。
- `console_reviewer.py` / `file_reviewer.py` / `null_reviewer.py`：`Reviewer` 的三种实现。

全貌见 `docs/spec/OVERVIEW.md` 与 `docs/spec/harness/SPEC.md`。本文件是统一出口。
"""

from __future__ import annotations

from .episode.episode_runtime import EpisodeRuntime
from .interface import GoalUpdate, PlannerOutcome, Reviewer
from .run.harness import RunHarness
from .run.run_state import RunState
from .run.runtime import RunRuntime
from .task.task_runtime import TaskRuntime

__all__ = [
    "EpisodeRuntime",
    "GoalUpdate",
    "PlannerOutcome",
    "Reviewer",
    "RunHarness",
    "RunRuntime",
    "RunState",
    "TaskRuntime",
]
