"""`TaskEntry`：episode 任务表的一行——一个拆出来的 task 与它在本局内的状态。

**task 只派一次**：失败后不重开，要重做就重拆（新条目、新 `task_id`）。所以没有
`GoalEntry` 的 `attempts` / `last_episode_id`——`task_id` 本身就对得上它的 `TaskOutput`
与 TaskMemory。多一列 `round`：第几版拆解，让 decomposer 看得出"第 1 版剩下的条目是
因为哪个失败被弃的"。

**表为准**：同 `GoalEntry`——`status` 是最终定案（含人审推翻），TaskMemory 的章保留机器判定。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain import Task

from .entry_status import EntryStatus


class TaskEntry(BaseModel):
    """任务表的一行。"""

    task: Task = Field(description="task 本体（`task_id` 由 harness 编：`{goal_id}-t{n}`）")
    status: EntryStatus = Field(
        default=EntryStatus.PENDING,
        description="本局内的状态。**至多一条 `RUNNING`**（episode.act 盖、review_and_judge 定案）",
    )
    note: str = Field(default="", description="放弃或人审推翻的理由")
    overturned: bool = Field(
        default=False, description="这条定案是人审推翻来的（与 TaskMemory 里的机器判定相反）"
    )
    round: int = Field(ge=1, description="第几版拆解产出的（从 1 起）")


__all__ = ["TaskEntry"]
