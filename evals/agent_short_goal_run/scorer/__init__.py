"""完整目标运行评分的协议、结论与指标出口。"""

from __future__ import annotations

from . import rules
from .metric import Metric, accuracy, stderr
from .registry import RULES, Check, judge, rule
from .score import Score, ScoreKind, from_check_verdict, from_red_line_hits
from .scorer import Scorer, mechanical_scorer, red_line_scorer, scorer_from_check
from .stream import Frame, RunStream

__all__ = [
    "RULES",
    "Check",
    "Frame",
    "RunStream",
    "judge",
    "rule",
    "rules",
    "Metric",
    "Score",
    "ScoreKind",
    "Scorer",
    "accuracy",
    "from_check_verdict",
    "from_red_line_hits",
    "mechanical_scorer",
    "red_line_scorer",
    "scorer_from_check",
    "stderr",
]
