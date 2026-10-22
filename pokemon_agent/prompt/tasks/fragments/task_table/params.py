"""task_table 的原始素材。"""

from pydantic import BaseModel

from ....records import TaskTableRecord


class TaskTableParams(BaseModel):
    entries: list[TaskTableRecord]
    serialized: bool = False
