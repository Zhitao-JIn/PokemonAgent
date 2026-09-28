"""判定与报表：一条样本的判定、红线、效率，整份报告的组装、渲染与对比。只做 re-export。"""

from __future__ import annotations

from .assemble import BAD_CASES, FORMS, HEADER, REPORT, RESULTS, build_report
from .diff import diff
from .evaluate import RUN_RECORD, evaluate
from .redlines import red_lines

__all__ = [
    "BAD_CASES",
    "FORMS",
    "HEADER",
    "REPORT",
    "RESULTS",
    "RUN_RECORD",
    "build_report",
    "diff",
    "evaluate",
    "red_lines",
]
