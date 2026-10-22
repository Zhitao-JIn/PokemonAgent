"""`JudgeFeedback`：本层上一次判定的反馈——模型怎么判的、人认没认、人的理由。

`review_and_judge` 写进本层 state，下一次 `plan_run` / `plan_episode` 原样放进
规划 / 拆解请求（`docs/web_reviewer/spec.md` §4.6）。走 state 不走 trace：
plan 只读 state 与记忆。
"""

from __future__ import annotations

from pydantic import Field

from .audit_verdict import AuditVerdict
from .judgement import Judgement


class JudgeFeedback(Judgement):
    """一次本层判定及人对它的表态。

    done / why：judge 模型的裁决与理由。
    audit：人对这条裁决的表态；**没问人**（模型判没成）时为 None。
    note：人推翻时给的理由；其余情况为空串。
    """

    audit: AuditVerdict | None = Field(
        default=None, description="人的表态；模型判没成时不问人，为 None"
    )
    note: str = Field(default="", description="人推翻时的理由")


__all__ = ["JudgeFeedback"]
