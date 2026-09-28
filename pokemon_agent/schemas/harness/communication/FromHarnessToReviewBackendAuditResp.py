"""`FromHarnessToReviewBackendAuditResp`：跳 A（后端 → 源程序）的审回话。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.harness.domain.audit_verdict import AuditVerdict


class FromHarnessToReviewBackendAuditResp(BaseModel):
    """后端交回的表态。`seq` 是后端给这一问编的号，进源程序日志。"""

    seq: int = Field(ge=1, description="后端给这一问的编号（全局单调、跨 run）")
    verdict: AuditVerdict = Field(description="认账 / 推翻")
    note: str = Field(default="", description="推翻时的理由")
    answered: bool = Field(description="人真的答了；False = 超时，回的是认账")


__all__ = ["FromHarnessToReviewBackendAuditResp"]
