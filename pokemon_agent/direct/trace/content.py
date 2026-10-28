"""每种账的正文（`content`）读回来的类型化形状——`render.py` 的镜像，字段名以渲染函数为准。

落盘时标量一律是字符串（`"15"` / `"true"`），这里按真实类型声明，读回时由 pydantic 宽松转换；
本来就是结构化数据的（`facts` / `sequence` / `tasks` / `ram` …）直接是对象。
除调用账（正文由 brain / world 各自拼，键随链路变）外，一律 `extra="forbid"`：
渲染层多出或改名一个键，读侧当场报错，而不是静默漏读
（`tests/direct/trace/test_trace_parse.py` 逐种账做"渲染 → 解析"回环）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from pokemon_agent.world import (
    Facts,
    PlaceInWorld,
    RamReadout,
    StepObservation,
    TakeoverView,
    TaskScene,
)


class _Content(BaseModel):
    """正文的公共基类：多一个键就报错。"""

    model_config = ConfigDict(extra="forbid")


class RunStartContent(_Content):
    goals: list[str]
    success_criteria: list[str]
    run_goal: str = ""
    run_criteria: str = ""


class RunEndContent(_Content):
    total: int
    succeeded: int
    termination: str
    judge_reason: str


class ErrorEndContent(_Content):
    """`run_error` / `episode_error` / `task_error`：只带异常快照。"""

    error: str


class EpisodeStartContent(_Content):
    goal_id: str
    goal: str
    success_criteria: str
    max_steps: int


class EpisodeEndContent(_Content):
    termination: str
    judge_reason: str
    tasks_used: int
    acts_used: int
    reason: str


class TaskStartContent(_Content):
    entry_id: str | None = None
    goal: str
    success_criteria: str
    max_steps: int
    total_acts: int


class TaskEndContent(_Content):
    entry_id: str | None = None
    termination: str
    judge_reason: str
    steps_used: int
    reason: str


class SenseFrameContent(_Content):
    status: str | None = None
    facts: Facts
    done: bool
    perceived: bool | None = None
    place: PlaceInWorld | None = None
    scene: TaskScene | None = None
    takeover: TakeoverView | None = None
    frame: str = ""
    ram: RamReadout | None = None


class Segment(BaseModel):
    """动作链的一段（`Action.segments()` 的 `model_dump()`）。"""

    model_config = ConfigDict(extra="allow")

    name: str
    times: int = 1


class ScriptCallContent(BaseModel):
    """脚本调用（`ScriptCall.model_dump()`）。"""

    name: str
    args: dict[str, str | int] = {}


class ChooseVerdictContent(_Content):
    sequence: list[Segment]
    script: ScriptCallContent | None = None
    human_note: str = ""


class ActCallContent(_Content):
    """`act_call` 的正文——key / script 两形（P5）：

    key 形只有 `sequence`；script 形只有 `script`/`args`/`ok`/`code`（+可选
    `data`/`events`/`dialog`/`observations`）。两形恰好一个非空，由解析器按字段区分。

    `dialog` 是脚本调用期间屏幕上依次出现的对话**行**（扁平报告里的按行列表，
    不是 `advance_dialog` 那份按段的 `data["dialog"]`）；按键形没有这个键。
    """

    sequence: list[Segment] = Field(default_factory=list)
    script: str | None = None
    args: dict[str, str | int] = Field(default_factory=dict)
    ok: str | None = None
    code: str | None = None
    data: dict[str, Any] | None = None
    events: list[dict[str, Any]] | None = None
    dialog: list[str] | None = None
    observations: list[StepObservation] | None = None


class CheckStallContent(_Content):
    stall_key: str
    stall_count: int


class JudgeVerdictContent(_Content):
    decision: str = ""
    judge_trigger: str = "normal"
    planning_round: str = ""
    termination: str
    fail_streak: str
    judge_reason: str
    audit: str
    human_note: str


class DecomposedTask(_Content):
    task_id: str
    goal: str
    success_criteria: str
    max_steps: int


class DecomposeVerdictContent(_Content):
    planning: dict[str, Any] | None = None
    planning_round: str | None = None
    execution_order: list[str] | None = None
    tasks: list[DecomposedTask]
    why: str
    human_note: str


class PlanVerdictContent(_Content):
    planning: dict[str, Any] | None = None
    planning_round: str | None = None
    execution_order: list[str] | None = None
    pushed_goals: list[str]
    updates: list[Any]
    why: str
    human_note: str


class VerifyVerdictContent(_Content):
    checked: int
    negative: int


class ModelCallContent(BaseModel):
    """九条链路的调用账：用量字段是公共的，其余键随链路而变（`why` / `verdicts` / `images`…）。"""

    model_config = ConfigDict(extra="allow")

    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    ok: bool = True
    error: str = ""


class CallFailedContent(_Content):
    link: str
    exception: str
    reason: str


class CallExhaustedContent(_Content):
    link: str


class SummaryParseErrorContent(_Content):
    link: str
    reason: str


class CheckpointSaveContent(_Content):
    level: str
    manifest_path: str


class CheckpointRestoreContent(_Content):
    level: str
    manifest_path: str


class SettleGoalContent(_Content):
    goal_id: str
    status: str
    episode_id: str
    attempts: int
    audit: str
    note: str
    overturned: bool
    fail_streak: str


class OtherContent(BaseModel):
    """本版读侧还没建模的账：原样保留全部键。"""

    model_config = ConfigDict(extra="allow")


class EventMeta(BaseModel):
    """封套 `meta`：落盘层盖 `run_id` / `branch`，其余由 harness 自报。"""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    branch: str = "main"
    source: str = ""
    episode_id: str = ""
    task_id: str = ""
    step: int = Field(default=0, ge=0)
    checkpoint_id: str = Field(default="", description="只有存档 / 恢复两本账带：连起新线与分叉点")


__all__ = [
    "ScriptCallContent",
    "CallExhaustedContent",
    "CallFailedContent",
    "CheckStallContent",
    "CheckpointRestoreContent",
    "CheckpointSaveContent",
    "ChooseVerdictContent",
    "DecomposeVerdictContent",
    "DecomposedTask",
    "EpisodeEndContent",
    "EpisodeStartContent",
    "ErrorEndContent",
    "EventMeta",
    "JudgeVerdictContent",
    "ModelCallContent",
    "OtherContent",
    "PlanVerdictContent",
    "ActCallContent",
    "RunEndContent",
    "RunStartContent",
    "Segment",
    "SenseFrameContent",
    "SettleGoalContent",
    "SummaryParseErrorContent",
    "TaskEndContent",
    "TaskStartContent",
    "VerifyVerdictContent",
]


class ReadRunMemoryContent(_Content):
    """run 记忆读账，形状与 episode 的 query/refs 检索账一致。"""

    query: str
    refs: list[str]
    timings: dict[str, float] | None = None


class IndexContent(_Content):
    headline: str = ""
    keys: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class WriteRunMemoryContent(_Content):
    """run 记忆派生正文，不含来源章坐标与计数。"""

    summary: str
    reason: str
    reusable_patterns: list[str]
    critical_decisions: list[str]
    failure_points: list[str]
    quality_score: float
    quality_rationale: str
    applicable_scenes: list[str]
    tags: list[str]
    markdown: str
    index: IndexContent
