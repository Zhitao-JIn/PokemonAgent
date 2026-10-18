"""只读查询的唯一注册表；体量上限约束单次返回，不约束可访问的历史范围。"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pokemon_agent.schemas.harness.domain.trace_kind import TraceKind

TRACE_QUERY_MAX_ROWS: int = 50
TRACE_QUERY_MAX_CONTENT: int = 2000
RECALL_QUERY_MAX_ROWS: int = 8
FRAME_QUERY_MAX_IMAGES: int = 2
RecallHint = Literal["episode_id", "map_id", "place", "run_id", "run_goal", "runs"]


class TraceQuery(BaseModel):
    """按 run 与非空标签等值过滤，从最新处向前翻页。"""

    model_config = ConfigDict(extra="forbid")

    tool: Literal["read_trace"] = "read_trace"
    run_id: str | None = Field(default=None, min_length=1)
    episode_id: str | None = Field(default=None, min_length=1)
    task_id: str | None = Field(default=None, min_length=1)
    source: str | None = Field(default=None, min_length=1)
    kind: TraceKind | None = None
    last_n: int = Field(default=20, ge=1, le=TRACE_QUERY_MAX_ROWS)
    offset: int = Field(default=0, ge=0)
    content_limit: int = Field(default=300, ge=0, le=TRACE_QUERY_MAX_CONTENT)


class RecallQuery(BaseModel):
    """探索跨 run 记忆；runs=all 仅列出 run 族，不与其他 hint 组合。"""

    model_config = ConfigDict(extra="forbid")

    tool: Literal["recall"] = "recall"
    query: str = ""
    conditions: dict[RecallHint, str] = Field(
        default_factory=dict,
        description="episode_id / map_id / place / run_id / run_goal，或单独 runs=all",
    )
    limit: int = Field(default=8, ge=1, le=RECALL_QUERY_MAX_ROWS)

    @model_validator(mode="after")
    def validate_hints(self) -> Self:
        """拒绝未知 hint 与会被底层忽略的 runs 组合。"""
        if "runs" in self.conditions and self.conditions != {"runs": "all"}:
            raise ValueError("runs 只接受单独的 runs=all")
        return self


class FrameQuery(BaseModel):
    """latest 取当前 run 最新 sense_frame；before/after 必须给 episode_id 与 step。"""

    model_config = ConfigDict(extra="forbid")

    tool: Literal["read_frame"] = "read_frame"
    episode_id: str | None = Field(default=None, min_length=1)
    step: int | None = Field(default=None, ge=0)
    which: Literal["before", "after", "latest"] = "after"

    @model_validator(mode="after")
    def validate_location(self) -> Self:
        """两种取帧模式的坐标互斥，非法外部输入用显式校验失败。"""
        if self.which == "latest":
            if self.episode_id is not None or self.step is not None:
                raise ValueError("latest 不接受 episode_id / step")
        elif self.episode_id is None or self.step is None:
            raise ValueError("before / after 必须给 episode_id 和 step")
        return self


class BrainFramesQuery(BaseModel):
    """当前 pending 问的大脑画面分页，由 hub 回答，不由 ViewReaders 查询。"""

    model_config = ConfigDict(extra="forbid")

    tool: Literal["read_brain_frames"] = "read_brain_frames"
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=FRAME_QUERY_MAX_IMAGES, ge=1, le=FRAME_QUERY_MAX_IMAGES)


ViewQuery = Annotated[
    TraceQuery | RecallQuery | FrameQuery | BrainFramesQuery, Field(discriminator="tool")
]


class ViewAnswer(BaseModel):
    """可直接展示的查询结果；只有显式取帧查询才携带 images。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    text: str
    images: list[str] = Field(default_factory=list, max_length=FRAME_QUERY_MAX_IMAGES)
