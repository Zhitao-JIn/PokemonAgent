"""core —— inspect-ai 真协议的薄适配（spec2 §二）。

`task` / `solver` / `evalset` 是真库 re-export（R0 实测口径，0.3.271）；
`score` / `scorer` / `metric` 是本项目判定货币（Score/Scorer/Metric，R2a 从 e2e/scoring 迁入，
R2b 换真库 Score 时判据/红线/投影逻辑不动）；`evallog` 承载 diff 口径校验（V9 的 header 载体）。
"""

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
