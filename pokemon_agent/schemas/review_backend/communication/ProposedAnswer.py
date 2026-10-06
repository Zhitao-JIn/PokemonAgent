"""`ProposedAnswer`：AI 复核席给的一笔结论——跳 B `proposal` 与跳 C `proposal` 共用同一模型。

与 `FromFrontendToReviewBackendAnswerReq` 同形（`text`/`verdict`/`note`），但不带 `seq`/`by`：
它只是一份"建议"，由后端转成跳 B 推送时套上 `seq` 与 `round`，由人改后再交回 `answer`。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.harness.domain.audit_verdict import AuditVerdict


class ProposedAnswer(BaseModel):
    """AI 复核席的结论草案。

    插话：填 `text`（`None` = "无意见"，与空串等价）。
    审：填 `verdict`（推翻时可带 `note`）。
    """

    text: str | None = Field(default=None, description="插话：AI 给的一句话意见")
    verdict: AuditVerdict | None = Field(default=None, description="审：AI 的认 / 推翻")
    note: str = Field(default="", description="审：推翻理由")


__all__ = ["ProposedAnswer"]
