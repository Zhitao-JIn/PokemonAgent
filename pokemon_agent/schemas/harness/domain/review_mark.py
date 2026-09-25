"""`ReviewMark`：问人两本账（`review_inject` / `review_audit`）的正文素材。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReviewMark(BaseModel):
    """一次问人的回话。插话取 `form_kind` + `reply`；审取 `verdict` + `note`。"""

    form_kind: str = Field(default="", description="插话：亮给人的是哪种表单")
    reply: str = Field(default="", description="插话：人说的话；空串 = 没意见")
    verdict: str = Field(default="", description="审：认 / 推翻（`AuditVerdict` 的值）")
    note: str = Field(default="", description="审：推翻时的理由")
