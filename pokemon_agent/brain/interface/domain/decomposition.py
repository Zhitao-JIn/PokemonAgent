"""递归规划提案；允许空新增，不具有终止权。"""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from .planning import PlannedTask, PlanningUpdate


class Decomposition(BaseModel):
    """调用方整版验证和采纳；未点名表项保留。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    PlannedTask: ClassVar[type[PlannedTask]] = PlannedTask
    PlanUpdate: ClassVar[type[PlanningUpdate]] = PlanningUpdate
    new_items: list[PlannedTask] = Field(default_factory=list)
    updates: list[PlanningUpdate] = Field(default_factory=list)
    execution_order: list[str] | None = None
    why: str = Field(min_length=1)

    @property
    def tasks(self) -> list[PlannedTask]:
        """内部转换读取新增项；序列化只输出 new_items。"""
        return self.new_items
