"""递归规划提案；允许空新增，不具有终止权。"""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from .planning import PlannedGoal, PlanningUpdate


class RunPlan(BaseModel):
    """调用方整版验证和采纳；未点名表项保留。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    PlanGoal: ClassVar[type[PlannedGoal]] = PlannedGoal
    PlanUpdate: ClassVar[type[PlanningUpdate]] = PlanningUpdate
    new_items: list[PlannedGoal] = Field(default_factory=list)
    updates: list[PlanningUpdate] = Field(default_factory=list)
    execution_order: list[str] | None = None
    why: str = Field(min_length=1)

    @property
    def push_goals(self) -> list[PlannedGoal]:
        """内部转换读取新增项；序列化只输出 new_items。"""
        return self.new_items
