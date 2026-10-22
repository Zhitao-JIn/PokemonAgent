"""逻辑 L2 目标表；执行身份、尝试次数与来源引用分别保存。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain import Task

from .entry_status import EntryStatus


class TaskEntry(BaseModel):
    """任务表的一行。"""

    entry_id: str = Field(min_length=1)
    attempts: int = Field(default=0, ge=0)
    last_task_id: str | None = None
    task: Task = Field(description="逻辑目标内容；派发时复制为具有独立 task_id 的执行任务")
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
