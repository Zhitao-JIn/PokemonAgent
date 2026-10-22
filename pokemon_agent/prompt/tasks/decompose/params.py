"""decompose 的独立原始素材契约。"""

from pydantic import BaseModel, Field

from ...objects import ObjectFactEvent
from ...observation import ObservationRecord
from ...records import (
    EpisodeRecord,
    GoalDefinition,
    JudgeFeedbackRecord,
    TaskRecord,
    TaskTableRecord,
)


class DecomposeParams(BaseModel):
    goal: GoalDefinition
    observation: ObservationRecord
    task_memories: list[TaskRecord] = Field(default_factory=list)
    task_table: list[TaskTableRecord] = Field(default_factory=list)
    episode_index: list[EpisodeRecord] = Field(default_factory=list)
    knowledge: list[str] = Field(default_factory=list)
    last_judge: JudgeFeedbackRecord | None = None
    max_tasks: int
    execution_order: list[str] = Field(default_factory=list)
    remaining_planning_rounds: int | None = None
    human_note: str = ""
    terrain_meanings: dict[str, str]

    known_objects: list[ObjectFactEvent] = Field(default_factory=list)
