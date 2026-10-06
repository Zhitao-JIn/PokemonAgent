"""evals 自产的契约：样本、判定、报告。只做 re-export。"""

from __future__ import annotations

from .report import COMPARABLE_FIELDS, BadCase, ReportHeader
from .sample import EvalSample, RedLine, Rubric, RubricItem, RubricLevel, SampleStart
from .verdict import (
    CheckVerdict,
    Efficiency,
    JudgeCell,
    JudgeCellName,
    Outcome,
    RedLineHit,
    RubricScore,
    SampleResult,
    SenseAgreement,
    TokenUse,
)

__all__ = [
    "COMPARABLE_FIELDS",
    "BadCase",
    "CheckVerdict",
    "Efficiency",
    "EvalSample",
    "JudgeCell",
    "JudgeCellName",
    "Outcome",
    "RedLine",
    "RedLineHit",
    "ReportHeader",
    "Rubric",
    "RubricItem",
    "RubricLevel",
    "RubricScore",
    "SampleResult",
    "SampleStart",
    "SenseAgreement",
    "TokenUse",
]
