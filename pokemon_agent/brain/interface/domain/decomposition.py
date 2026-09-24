"""`Decomposition`：`Brain.decompose()` 从模型输出解析出的**任务链**（episode 级规划）。

一个目标拆成按执行顺序排好的若干 task。`task_id` 不在这里——身份由调用方
（harness 的 `plan_episode`）按 `{goal.task_id}-t{n}` 编，brain 只给内容。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Decomposition(BaseModel):
    """一版任务链 + 规划说明。"""

    class PlannedTask(BaseModel):
        """链上的一个 task。"""

        goal: str = Field(min_length=1, description="这个 task 要达成什么，一句话")
        success_criteria: str = Field(min_length=1, description="怎么算做成")
        max_steps: int = Field(gt=0, description="这个 task 最多按几个键")

    tasks: list[PlannedTask] = Field(min_length=1, description="任务链，按执行顺序；至少一条")
    why: str = Field(default="", description="为什么这样拆")


__all__ = ["Decomposition"]
