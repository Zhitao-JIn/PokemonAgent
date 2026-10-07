"""统一判定结果 `Score`（spec2 §六）：三套旧判定协议收敛的载体。

形状对齐 inspect-ai 的 `Score`（value / explanation / metadata），本项目的等价物：
`outcome`（verdict 型：pass / fail / unjudgeable）、`score`（graded 型：rubric 档位）、
`evidence`（最小可归因的事件 uuid，inspect 里进 metadata）。
`kind` 把 verdict 型与 graded 型**机械分列**（V3：model-graded 的档位分不混进机械成功率）。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from evals.scorers.verdict import CheckVerdict, Outcome, RedLineHit

ScoreKind = Literal["verdict", "graded"]
"""verdict = 判成/判负（进成功率）；graded = rubric 档位（分列，只作参照）。"""


class Score(BaseModel):
    """一个 scorer 对一条样本的一次判定。

    契约：`kind="verdict"` 时 `outcome` 必填、`score` 必须为 None、`sample_id` 必填
    （metric 按样本聚合的键）；`kind="graded"` 时 `score` 必填、`outcome` 必须为 None。

    `value` 是指标的数值读口：pass=1.0 / fail=0.0 / unjudgeable=None（不进指标分母）；
    graded 型 = 档位原样（只供路径层聚合，不进成功率）。
    """

    scorer_id: str = Field(
        description="谁打的：mech:<check_id> / red_lines / judge_agreement / model:<item_id>"
    )
    kind: ScoreKind = "verdict"
    outcome: Outcome | None = None
    score: int | None = None
    evidence: list[str] = Field(default_factory=list, description="支撑结论的事件 uuid")
    reason: str = ""
    sample_id: str = ""
    epoch: int = Field(default=0, ge=0, description="epochs>1 的圈号；k=1 恒 0")
    detail: dict[str, Any] = Field(
        default_factory=dict, description="分列结果 / judge 四格 / rubric 原始量"
    )

    @model_validator(mode="after")
    def _kind_matches_payload(self) -> Score:
        """kind 与载明的结论字段一一对应，分列不许漏。"""
        if self.kind == "verdict":
            assert self.outcome is not None, "verdict 型 Score 必须带 outcome"
            assert self.score is None, "verdict 型 Score 不带 rubric 档位（分列，V3）"
            assert self.sample_id, "verdict 型 Score 必须带 sample_id（metric 聚合键）"
        else:
            assert self.score is not None, "graded 型 Score 必须带 score"
            assert self.outcome is None, "graded 型 Score 不判 pass/fail（分列，V3）"
        return self

    @property
    def value(self) -> float | None:
        """指标的数值读口。"""
        if self.kind == "graded":
            return float(self.score) if self.score is not None else None
        if self.outcome == "pass":
            return 1.0
        if self.outcome == "fail":
            return 0.0
        return None


def from_check_verdict(
    scorer_id: str, verdict: CheckVerdict, *, sample_id: str, epoch: int = 0
) -> Score:
    """`CheckVerdict` → Score（机械判据适配，证据 uuid 原样进 evidence）。"""
    return Score(
        scorer_id=scorer_id,
        kind="verdict",
        outcome=verdict.outcome,
        evidence=verdict.evidence,
        reason=verdict.reason,
        sample_id=sample_id,
        epoch=epoch,
    )


def from_red_line_hits(hits: list[RedLineHit], *, sample_id: str, epoch: int = 0) -> Score:
    """红线命中 → 一条判负的 Score（spec2 §六：命中即判负；未命中即"无违规"）。

    命中明细整体进 `detail["hits"]` 分列，不与机械判定混权。
    """
    if not hits:
        return Score(
            scorer_id="red_lines", outcome="pass", reason="红线全空",
            sample_id=sample_id, epoch=epoch,
        )  # fmt: skip
    return Score(
        scorer_id="red_lines",
        outcome="fail",
        evidence=[u for h in hits for u in h.evidence],
        reason="；".join(f"{h.line_id}：{h.reason}" for h in hits),
        detail={"hits": [h.model_dump() for h in hits]},
        sample_id=sample_id,
        epoch=epoch,
    )


__all__ = ["Score", "ScoreKind", "from_check_verdict", "from_red_line_hits"]
