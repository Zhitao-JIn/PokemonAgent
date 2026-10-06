"""`FromReviewBackendToFrontendProposalReq`：跳 B（后端 → 网页）推一笔 AI 复核席的结论。无回话。

后端把 agent 进程经跳 C 推回的 `proposal` 转成这一封广播给网页；网页填入结论框并刷新聊天栏。
`round`：0 为首轮（seed 推回），每轮「发给 AI」+1。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .ProposedAnswer import ProposedAnswer


class FromReviewBackendToFrontendProposalReq(BaseModel):
    """一笔 AI 复核席的结论草案。"""

    msg: Literal["proposal"] = Field(default="proposal", description="消息标签：`/ui` 上据此分流")
    seq: int = Field(ge=1, description="这一笔结论对应第几问")
    proposal: ProposedAnswer = Field(description="AI 给的结论草案")
    round: int = Field(default=0, ge=0, description="讨论轮次：0 为首轮，每轮「发给 AI」+1")


__all__ = ["FromReviewBackendToFrontendProposalReq"]
