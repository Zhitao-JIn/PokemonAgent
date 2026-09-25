"""`FromFrontendToReviewBackendAnswerReq`：跳 B（网页 → 后端）答一问。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from pokemon_agent.schemas.harness.domain.audit_verdict import AuditVerdict


class FromFrontendToReviewBackendAnswerReq(BaseModel):
    """人的答案。插话填 `text`（空串 = 没意见）；审填 `verdict`（推翻时可带 `note`）。"""

    msg: Literal["answer"] = Field(default="answer", description="消息标签")
    seq: int = Field(ge=1, description="答的是第几问")
    text: str | None = Field(default=None, description="插话：人说的话")
    verdict: AuditVerdict | None = Field(default=None, description="审：认 / 推翻")
    note: str = Field(default="", description="审：推翻理由")


__all__ = ["FromFrontendToReviewBackendAnswerReq"]
