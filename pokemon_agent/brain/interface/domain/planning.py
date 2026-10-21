"""递归规划的结构契约：显式预算、定点修订与完整执行顺序。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PlanningUpdate(BaseModel):
    """修改调用方表快照的一行；运行事实不可由规划器填写。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    index: int = Field(ge=0)
    status: Literal["pending", "abandoned"]
    note: str = Field(min_length=1)


class TaskBudget(BaseModel):
    """L1 子目标的单次 task 派发额度。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    limit: int = Field(gt=0)
    unit: Literal["tasks"]


class ActionBudget(BaseModel):
    """L2 子目标的单次动作额度。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    limit: int = Field(gt=0)
    unit: Literal["actions"]


class PlannedGoal(BaseModel):
    """规划器提出的 L1 目标；身份由调用方分配。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    goal: str = Field(min_length=1)
    success_criteria: str = Field(min_length=1)
    budget: TaskBudget

    @property
    def max_steps(self) -> int:
        """向执行 Task 转换时使用的额度。"""
        return self.budget.limit


class PlannedTask(BaseModel):
    """规划器提出的 L2 目标；身份由调用方分配。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    goal: str = Field(min_length=1)
    success_criteria: str = Field(min_length=1)
    budget: ActionBudget

    @property
    def max_steps(self) -> int:
        """向执行 Task 转换时使用的额度。"""
        return self.budget.limit
