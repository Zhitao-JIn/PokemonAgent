"""`FromHarnessToReviewBackendAuditResp`：跳 A（后端 → 源程序）的审回话。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from pokemon_agent.schemas.harness.domain.audit_verdict import AuditVerdict


class FromHarnessToReviewBackendAuditResp(BaseModel):
    """后端交回的表态。`seq` 是后端给这一问编的号，进源程序日志。"""

    seq: int = Field(ge=1, description="后端给这一问的编号（全局单调、跨 run）")
    verdict: AuditVerdict = Field(description="认账 / 推翻")
    note: str = Field(default="", description="推翻时的理由")
    answered: bool = Field(description="是否有人或 AI 作答；False 表示默认回话，by 为 none")
    by: Literal["human", "agent", "none"] = Field(
        description="回话来源：human 人作答、agent AI 作答、none 无人作答"
    )

    @model_validator(mode="after")
    def validate_answered(self) -> FromHarnessToReviewBackendAuditResp:
        """回话来源与是否作答必须一致；不一致时拒绝构造。"""
        if self.answered != (self.by != "none"):
            raise ValueError('answered must equal (by != "none")')
        return self


__all__ = ["FromHarnessToReviewBackendAuditResp"]
