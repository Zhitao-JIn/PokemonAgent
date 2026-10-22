"""`EntryStatus`：run 目标表（`GoalEntry`）与 episode 任务表（`TaskEntry`）共用的**状态**。

两层的五个状态含义完全相同；不同的只是"谁能改成什么"，那条权限写在各层改状态的代码里：

| 变化 | goal（run） | task（episode） |
|---|---|---|
| `PENDING → RUNNING` | `run.act` 派发 | `episode.act` 派发 |
| `RUNNING → COMPLETED / FAILED` | `run.review_and_judge` 盖章 | `episode.review_and_judge` 盖章 |
| 人审推翻 | 盖反面、`overturned=True` | 同左 |
| `FAILED / BLOCKED / ABANDONED → PENDING` | plan 显式重开 | decompose 显式重开，产生新执行 |
| `PENDING → ABANDONED` | planner 主观放弃 | decomposer 主观放弃，失败不自动清空剩余条目 |

`COMPLETED` / `FAILED` **只能由 harness 盖章**（机械事实 + 人审表态），LLM 不直接写。
"""

from __future__ import annotations

from enum import StrEnum


class EntryStatus(StrEnum):
    """一行（目标或 task）在本层内的状态。"""

    BLOCKED = "blocked"
    PENDING = "pending"
    """待派发：还没跑过，或由本层规划器显式重开。"""
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
