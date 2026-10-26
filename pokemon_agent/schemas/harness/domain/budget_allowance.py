"""调度方提供的预算素材；建议与配置硬限保持独立，不承载停机逻辑。"""

from typing import Literal

from pydantic import BaseModel, Field, computed_field


class BudgetAllowance(BaseModel):
    """来源明确的本层额度；used可超建议，remaining耗尽不代表任务完成。"""

    kind: Literal["advisory", "hard"]
    scope: Literal["run", "episode", "task"]
    unit: Literal["episodes", "tasks", "actions", "rounds", "seconds"]
    source: str = Field(min_length=1)
    limit: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    used: float = Field(default=0, ge=0, allow_inf_nan=False)

    @computed_field
    @property
    def remaining(self) -> float | None:
        """未设上限返回None，耗尽返回0；超出建议仍保留真实used。"""
        return None if self.limit is None else max(0, self.limit - self.used)
