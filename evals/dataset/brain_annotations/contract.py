"""逐例审阅契约：有标签、前提冲突、证据不足分别统计。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from evals.dataset.brain_calls.dataset_contract import Criterion
from evals.dataset.brain_choose.schemas import ActionMatcher


class Evidence(BaseModel):
    """request 内 JSON pointer 对应的原值摘要与完整值指纹。"""

    model_config = ConfigDict(extra="forbid")
    pointer: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    excerpt: str


class Annotation(BaseModel):
    """真值只给评分方；排除项不能伪装成负标签或进入分母。"""

    model_config = ConfigDict(extra="forbid")
    case_id: str
    family: Literal["choose", "judge", "plan", "decompose"]
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["labelled", "invalid_task", "unjudgeable"]
    method: Literal["mechanical_preexisting", "codex_history_review"]
    evaluation_mode: Literal["exact", "advisory"] = "exact"
    rationale: str = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)
    achieved: bool | None = None
    acceptable: list[ActionMatcher] = Field(default_factory=list)
    criteria: list[Criterion] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_label(self) -> "Annotation":
        """拒绝缺失真值、混用真值与排除项携带答案的外部记录。"""
        if self.status == "labelled" and self.evaluation_mode == "advisory":
            if self.family == "judge" or self.achieved is not None or not self.criteria:
                raise ValueError("advisory labels need criteria, not a binary truth")
            if self.family != "choose" and self.acceptable:
                raise ValueError("only choose can carry suggested actions")
            return self
        present = (self.achieved is not None, bool(self.acceptable), bool(self.criteria))
        expected = (
            (self.family == "judge", self.family == "choose", self.family in {"plan", "decompose"})
            if self.status == "labelled"
            else (False, False, False)
        )
        if present != expected:
            raise ValueError("annotation status/family/answer mismatch")
        return self
