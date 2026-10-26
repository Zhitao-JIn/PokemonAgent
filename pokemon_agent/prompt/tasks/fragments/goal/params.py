"""目标正文的共享原料，保留目标全文及当前目标标记。"""

from pydantic import BaseModel

from ....records import GoalDefinition


class GoalParams(BaseModel):
    entries: list[GoalDefinition]
    current_index: int | None = None
