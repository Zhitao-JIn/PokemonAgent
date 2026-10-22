"""run_plan 的独立原始素材契约。"""

from pydantic import BaseModel, Field

from ...objects import ObjectFactEvent
from ...observation import ObservationRecord
from ...records import (
    EpisodeRecord,
    GoalDefinition,
    GoalRecord,
    JudgeFeedbackRecord,
    RunRecord,
)


class RunPlanParams(BaseModel):
    run_goal: GoalDefinition
    plan: list[GoalRecord] = Field(default_factory=list)
    details: list[EpisodeRecord] = Field(default_factory=list)
    run_index: list[RunRecord] = Field(default_factory=list)
    knowledge: list[str] = Field(default_factory=list)
    observation: ObservationRecord | None = None
    objects: list[ObjectFactEvent] = Field(default_factory=list)
    last_judge: JudgeFeedbackRecord | None = None
    max_push: int
    human_note: str = ""
    execution_order: list[str] = Field(default_factory=list)
    remaining_planning_rounds: int | None = None
