"""`FromHarnessToReviewerAuditResp`：`Reviewer.audit()` 交回 harness 的表态。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.harness.domain.audit_verdict import AuditVerdict


class FromHarnessToReviewerAuditResp(BaseModel):
    """人的表态。

    `verdict` 是认还是推翻；`note` 是推翻时的理由——harness 把它写进表里那一行
    （审结果）或本层 `last_judge`（审裁决），下一次 plan 看得见。
    `answered=False`：没人答（超时 / 后端断连 / 无人值守），此时恒为认账。
    """

    verdict: AuditVerdict = Field(description="认账 / 推翻")
    note: str = Field(default="", description="推翻时的理由；认账时为空")
    answered: bool = Field(description="人真的答了；False = 回的是默认值（认账）")


__all__ = ["FromHarnessToReviewerAuditResp"]
