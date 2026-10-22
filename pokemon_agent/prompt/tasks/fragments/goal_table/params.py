"""goal_table 的原始素材。"""

from pydantic import BaseModel

from ....records import GoalRecord


class GoalTableParams(BaseModel):
    entries: list[GoalRecord]
    serialized: bool = False
