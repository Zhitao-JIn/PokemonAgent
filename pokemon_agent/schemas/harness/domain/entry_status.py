"""`EntryStatus`：run 目标表（`GoalEntry`）与 episode 任务表（`TaskEntry`）共用的**状态**。

两层的五个状态含义完全相同；不同的只是"谁能改成什么"，那条权限写在各层改状态的代码里：

| 变化 | goal（run） | task（episode） |
|---|---|---|
| `PENDING → RUNNING` | `run.act` 派发 | `episode.act` 派发 |
| `RUNNING → COMPLETED / FAILED` | `run.review_and_judge` 盖章 | `episode.review_and_judge` 盖章 |
| 人审推翻 | 盖反面、`overturned=True` | 同左 |
| `FAILED / ABANDONED → PENDING` | `plan_run` 显式重开 | **不允许**，要重做就重拆（新条目） |
| `PENDING → ABANDONED` | planner 或人的主观放弃 | 上一个 task 定案为失败后，harness 放弃剩余条目 |

`COMPLETED` / `FAILED` **只能由 harness 盖章**（机械事实 + 人审表态），LLM 不直接写。
"""

from __future__ import annotations

from enum import StrEnum


class EntryStatus(StrEnum):
    """一行（目标或 task）在本层内的状态。"""

    PENDING = "pending"
    """待派发：还没跑过，或被 `plan_run` 重开（只有 goal 能重开）。"""
    RUNNING = "running"
    """正在跑：已派发、还没定案。**全表至多一条**。"""
    COMPLETED = "completed"
    """定案为达成（harness 盖章；可能是人审推翻来的，见 `overturned`）。"""
    FAILED = "failed"
    """定案为没成（harness 盖章；不自动重派）。"""
    ABANDONED = "abandoned"
    """不做了：主观放弃，或前提已失效（上一个 task 失败后剩下的条目）。"""

    @property
    def is_active(self) -> bool:
        """这一行还算不算"后面要做的事"——`PENDING` / `RUNNING` 才是。"""
        return self in (EntryStatus.PENDING, EntryStatus.RUNNING)


__all__ = ["EntryStatus"]
