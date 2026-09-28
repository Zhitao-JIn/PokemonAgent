"""`AuditVerdict`：人对一条结论的表态——**认**或**推翻**。

三跳共用：进程内 `FromHarnessToReviewerAuditResp`、跳 A（源程序 ↔ 后端）、
跳 B（后端 ↔ 网页）都用它；落到表上的状态改写仍由 harness 盖章，人不写状态。
"""

from __future__ import annotations

from enum import StrEnum


class AuditVerdict(StrEnum):
    """人对一条结论的表态。**只有两个值**——"认"与"推翻"。"""

    ACCEPT = "accept"
    """认账：接受这条结论，harness 照它盖章。"""
    OVERTURN = "overturn"
    """推翻：这条结论不对，harness 按相反方向盖章（或作废 `GOAL_DONE`）。"""


__all__ = ["AuditVerdict"]
