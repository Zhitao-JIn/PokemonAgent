"""摘要评测边界：精确请求、候选正文与独立模型审阅结果。"""

from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from pokemon_agent.brain.interface import EpisodeSummary, RunSummary
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolSummarizeReq,
    FromHarnessToBrainToolSummarizeRunReq,
    FromHarnessToBrainToolSummarizeTaskReq,
)

Layer = Literal["task", "episode", "run"]
EvidenceText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
SummaryRequest: TypeAlias = (
    FromHarnessToBrainToolSummarizeTaskReq
    | FromHarnessToBrainToolSummarizeReq
    | FromHarnessToBrainToolSummarizeRunReq
)
SummaryAnswer: TypeAlias = EpisodeSummary | RunSummary
Dimension = Literal[
    "factual_fidelity", "key_information", "causal_reasoning", "reusability", "consistency_brevity"
]
DIMENSIONS: tuple[Dimension, ...] = (
    "factual_fidelity",
    "key_information",
    "causal_reasoning",
    "reusability",
    "consistency_brevity",
)
LAYERS: tuple[Layer, ...] = ("task", "episode", "run")


class DimensionReview(BaseModel):
    """一个维度的连续质量评价；未知保留为空，不猜测。"""

    model_config = ConfigDict(extra="forbid")
    name: Dimension
    score: float | None = Field(ge=0, le=1, strict=True, allow_inf_nan=False)
    source_evidence: EvidenceText
    candidate_evidence: EvidenceText
    reason: EvidenceText


class DistortionReview(BaseModel):
    """重大失真单独裁定；来源与候选证据不可省略。"""

    model_config = ConfigDict(extra="forbid")
    present: bool | None = Field(strict=True)
    source_evidence: EvidenceText
    candidate_evidence: EvidenceText
    reason: EvidenceText


class SummaryReview(BaseModel):
    """一次独立审阅；调用方还须核对维度完整且不重复。"""

    model_config = ConfigDict(extra="forbid")
    dimensions: list[DimensionReview]
    major_distortion: DistortionReview
