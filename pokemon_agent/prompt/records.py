"""Prompt 的独立记忆原料契约，与存储模型互不依赖。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ActRecord(BaseModel):
    class Observation(BaseModel):
        class Facts(BaseModel):
            model_config = ConfigDict(extra="allow")

            class Landmark(BaseModel):
                kind: str
                map_id: int
                x: int
                y: int

            class BattleStatus(BaseModel):
                class Combatant(BaseModel):
                    name: str
                    level: int
                    hp: int
                    max_hp: int
                    status: str

                mine: Combatant
                foe: Combatant

            scene: str | None = None
            overlay: str | None = None
            where: str = ""
            facing: str = ""
            neighbors: str = ""
            landmarks: list[Landmark] = Field(default_factory=list)
            dialog_text: str = ""
            options: list[str] = Field(default_factory=list)
            cursor: str | None = None
            overview: str = ""
            walk_map: str = ""
            map_id: int | None = None
            screen: str = ""
            neighbor_cells: dict[str, str] = Field(default_factory=dict)
            cells: list[str] = Field(default_factory=list)
            option_grid: list[list[str]] = Field(default_factory=list)
            cursor_cell: tuple[int, int] | None = Field(default=None)
            option_annotations: list[str] = Field(default_factory=list)
            battle_status: BattleStatus | None = Field(default=None)
            terrain_visible: bool = Field(default=False)

            @property
            def scene_value(self) -> str:
                """`scene` 的文本值；`scene` 为 `None` 时给空串。同真身
                `Facts.scene_value`——给只要文本的调用方用（知识检索 query）。"""
                return self.scene or ""

            @property
            def overlay_value(self) -> str:
                """同 `scene_value`，针对 `overlay`。"""
                return self.overlay or ""

        class Place(BaseModel):
            map_id: int
            x: int
            y: int

        step: int = Field()
        place: Place | None = Field(default=None)
        status: str = Field(default="")
        scene: str = Field(default="")
        facts: Facts = Field(default_factory=Facts)
        done: bool = Field(default=False)
        perceived: bool = Field(default=True)
        observation_flags: list[str] = Field(default_factory=list)

    before: Observation = Field()
    action: str = Field()
    after: Observation = Field()
    result: str = Field(default="")
    dialog: list[str] = Field(
        default_factory=list,
        description="脚本调用期间屏幕上依次出现的对话行（一行一个元素，不截断）；"
        "按键动作与旧记忆为空列表",
    )
    step: int = Field()
    episode_id: str = Field()
    task_id: str = Field(default="")
    run_id: str = Field(default="")
    before_frame: str | None = Field(default=None)
    after_frame: str | None = Field(default=None)


class TaskRecord(BaseModel):
    run_id: str = Field()
    episode_id: str = Field()
    entry_id: str | None = Field(default=None)
    task_id: str = Field()
    goal: str = Field()
    termination: str = Field(default="")
    reason: str = Field(default="")
    steps_used: int = Field(ge=0)
    total_acts: int = Field(ge=0)
    summary: str = Field()
    reusable_patterns: list[str] = Field(default_factory=list)
    critical_decisions: list[str] = Field(default_factory=list)
    failure_points: list[str] = Field(default_factory=list)
    quality_score: float = Field(ge=0.0, le=1.0)
    quality_rationale: str = Field()
    tags: list[str] = Field(default_factory=list)
    first_frame: str | None = Field(default=None)
    last_frame: str | None = Field(default=None)
    markdown: str = Field(default="")

    @property
    def success(self) -> bool:
        """成没成——由 `termination` 推出（`goal_done` 即达成），不单独存。"""
        return self.termination == "goal_done"


class EpisodeRecord(BaseModel):
    episode_id: str = Field()
    run_id: str = Field()
    run_goal: str = Field(default="")
    goal_id: str = Field(default="")
    goal: str = Field()
    steps: int = Field(ge=0)
    acts_used: int = Field(default=0, ge=0)
    termination: str = Field(default="")
    reason: str = Field(default="")
    summary: str = Field()
    reusable_patterns: list[str] = Field(default_factory=list)
    critical_decisions: list[str] = Field(default_factory=list)
    failure_points: list[str] = Field(default_factory=list)
    quality_score: float = Field(ge=0.0, le=1.0)
    quality_rationale: str = Field()
    applicable_scenes: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    first_frame: str | None = Field(default=None)
    last_frame: str | None = Field(default=None)
    markdown: str = Field(default="")

    @property
    def success(self) -> bool:
        """成没成——由 `termination` 推出（`goal_done` 即达成），不单独存。"""
        return self.termination == "goal_done"


class RunRecord(BaseModel):
    run_id: str = Field()
    run_goal: str = Field()
    episodes: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    acts_used: int = Field(default=0, ge=0)
    termination: str = Field(default="")
    reason: str = Field(default="")
    summary: str = Field()
    reusable_patterns: list[str] = Field(default_factory=list)
    critical_decisions: list[str] = Field(default_factory=list)
    failure_points: list[str] = Field(default_factory=list)
    quality_score: float = Field(ge=0.0, le=1.0)
    quality_rationale: str = Field()
    applicable_scenes: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    markdown: str = Field(default="")

    @property
    def success(self) -> bool:
        """仅 termination 为 goal_done 时成功。"""
        return self.termination == "goal_done"


class VerdictRecord(BaseModel):
    index: int
    positive: bool
    why: str


class TaskSpecRecord(BaseModel):
    task_id: str
    goal: str
    success_criteria: str = ""
    max_steps: int = 1
    initial_state_hint: str = ""


class GoalRecord(BaseModel):
    task: TaskSpecRecord
    status: str = "pending"
    attempts: int = 0
    last_episode_id: str | None = None
    note: str = ""
    overturned: bool = False


class GoalDefinition(BaseModel):
    goal: str
    criteria: str


class TaskTableRecord(BaseModel):
    entry_id: str
    attempts: int = 0
    last_task_id: str | None = None
    task: TaskSpecRecord
    status: str = "pending"
    note: str = ""
    overturned: bool = False
    round: int


class JudgeFeedbackRecord(BaseModel):
    decision: str
    why: str
    audit: str | None = None
    note: str = ""


class PlanningBudgetRecord(BaseModel):
    limit: int
    unit: str


class PlannedRecord(BaseModel):
    goal: str
    success_criteria: str
    budget: PlanningBudgetRecord


class PlanningUpdateRecord(BaseModel):
    index: int
    status: str
    note: str


class PlanningRecord(BaseModel):
    new_items: list[PlannedRecord] = Field(default_factory=list)
    updates: list[PlanningUpdateRecord] = Field(default_factory=list)
    execution_order: list[str] | None = None
    why: str
