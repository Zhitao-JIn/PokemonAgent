"""judge_success 的独立原始素材契约。"""

from pydantic import BaseModel, Field

from ...objects import ObjectFactEvent
from ...observation import ObservationRecord
from ...records import (
    ActRecord,
    EpisodeRecord,
    GoalDefinition,
    GoalRecord,
    PlanningRecord,
    RunRecord,
    TaskRecord,
    TaskTableRecord,
)


class JudgeParams(BaseModel):
    goal: GoalDefinition
    goal_table: list[GoalRecord] = Field(default_factory=list)
    latest_planning: PlanningRecord | None = None
    planning_round: int = 0
    trigger: str = ""
    history: list[ActRecord] = Field(default_factory=list)
    task_memories: list[TaskRecord] = Field(default_factory=list)
    task_table: list[TaskTableRecord] = Field(default_factory=list)
    episode_memories: list[EpisodeRecord] = Field(default_factory=list)
    task_index: list[TaskRecord] = Field(default_factory=list)
    episode_index: list[EpisodeRecord] = Field(default_factory=list)
    run_index: list[RunRecord] = Field(default_factory=list)
    observation: ObservationRecord | None = None
    knowledge: str = ""
    allow_interrupt: bool = False

    known_objects: list[ObjectFactEvent] = Field(default_factory=list)
