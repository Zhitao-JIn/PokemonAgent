"""完整目标运行评分的协议、结论与指标出口。"""

from __future__ import annotations

from .metric import Metric, accuracy, stderr
from .score import Score, ScoreKind, from_check_verdict, from_red_line_hits
from .scorer import Scorer, mechanical_scorer, red_line_scorer, scorer_from_check

__all__ = [
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
