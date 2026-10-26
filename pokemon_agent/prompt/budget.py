"""调度方提供的预算素材；建议与配置硬限保持独立，不承载停机逻辑。"""

from typing import Literal

from pydantic import BaseModel, Field, computed_field


class BudgetRecord(BaseModel):
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


def render_budgets(entries: list[BudgetRecord]) -> str:
    """按原始额度逐行渲染；缺素材不补造配置上限。"""
    if not entries:
        return "（未提供预算素材，不推测硬上限）"
    return "\n".join(
        f"{'父级建议' if entry.kind == 'advisory' else '配置硬限'} | "
        f"范围={entry.scope} | 单位={entry.unit} | 来源={entry.source} | "
        f"额度={entry.limit if entry.limit is not None else '不限'} | "
        f"已用={entry.used} | 剩余={entry.remaining if entry.remaining is not None else '不限'}"
        for entry in entries
    )
