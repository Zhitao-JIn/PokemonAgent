"""决策的独立原料及帧、脚本签名。"""

from pydantic import BaseModel, Field

from ...actions import ActionSpaceRecord
from ...budget import BudgetRecord
from ...objects import ObjectFactEvent
from ...observation import ObservationRecord
from ...records import ActRecord, ChangeRecord, GoalDefinition, TaskRecord


class DecideActionParams(BaseModel):
    goals: list[GoalDefinition]
    observation: ObservationRecord
    space: ActionSpaceRecord
    memories: list[ActRecord] = Field(default_factory=list)
    knowledge: str = ""
    task_index: list[TaskRecord] = Field(default_factory=list)
    last_result: str = ""
    last_outcome: ActRecord.Outcome | None = None
    last_changes: list[ChangeRecord] = Field(default_factory=list)
    budget_context: list[BudgetRecord] = Field(default_factory=list)
    human_note: str = ""
    max_segments: int
    terrain_meanings: dict[str, str]
    known_objects: list[ObjectFactEvent] = Field(default_factory=list)
