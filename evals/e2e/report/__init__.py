"""判定与报表：样本判定（统一 Scorer → 报告投影）、效率，报告的组装、渲染与对比。只做 re-export。"""

from __future__ import annotations

from evals.core.evallog import diff

from .assemble import BAD_CASES, FORMS, HEADER, REPORT, RESULTS, build_report
from .evaluate import (
    RUN_RECORD,
    RUN_RESULT,
    evaluate,
    hits_of,
    load_result,
    stall_limits_of,
    verdict_of,
)

__all__ = [
    "BAD_CASES",
    "FORMS",
    "HEADER",
    "REPORT",
    "RESULTS",
    "RUN_RECORD",
    "RUN_RESULT",
    "build_report",
    "diff",
    "evaluate",
    "hits_of",
    "load_result",
    "stall_limits_of",
    "verdict_of",
]
