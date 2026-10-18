"""`FromHarnessToReviewerAuditResp`：`Reviewer.audit()` 交回 harness 的表态。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from pokemon_agent.schemas.harness.domain.audit_verdict import AuditVerdict


class FromHarnessToReviewerAuditResp(BaseModel):
    """复核席的表态。

    `verdict` 是认还是推翻；`note` 是推翻时的理由，harness 写进本层 `last_judge`，
    下一次 plan 看得见。
    `answered=False`：没人答（超时 / 后端断连 / 无人值守），此时恒为认账。
    """

    verdict: AuditVerdict = Field(description="认账 / 推翻")
    note: str = Field(default="", description="推翻时的理由；认账时为空")
    answered: bool = Field(description="是否有人或 AI 作答；False 表示默认回话，by 为 none")
    by: Literal["human", "agent", "none"] = Field(
        description="回话来源：human 人作答、agent AI 作答、none 无人作答"
    )

    @model_validator(mode="after")
    def validate_answered(self) -> FromHarnessToReviewerAuditResp:
        """回话来源与是否作答必须一致；不一致时拒绝构造。"""
        if self.answered != (self.by != "none"):
            raise ValueError('answered must equal (by != "none")')
        return self


__all__ = ["FromHarnessToReviewerAuditResp"]
