"""路径层 rubric（v1 打分）：③ 代码算原始量，① ② 人工打分表。只做 re-export。"""

from __future__ import annotations

from .forms import DECOMPOSE, SCORES_FILE, STRATEGY, form_section, human_scores
from .redundant import ITEM_ID as REDUNDANT
from .redundant import score_redundant_path

__all__ = [
    "DECOMPOSE",
    "REDUNDANT",
    "SCORES_FILE",
    "STRATEGY",
    "form_section",
    "human_scores",
    "score_redundant_path",
]
