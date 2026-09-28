"""`FromFrontendToReviewBackendAnswerResp`：跳 B（后端 → 网页）答案回执。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FromFrontendToReviewBackendAnswerResp(BaseModel):
    """收下没有。`ok=False` 时 `reason` 说明：已被别处答了 / 已作废 / 没有这一问 / 答案与问不配。"""

    msg: Literal["answer_ack"] = Field(default="answer_ack", description="消息标签")
    seq: int = Field(ge=1, description="回执的是第几问")
    ok: bool = Field(description="答案是否被采纳")
    reason: str = Field(default="", description="不采纳的原因")


__all__ = ["FromFrontendToReviewBackendAnswerResp"]
