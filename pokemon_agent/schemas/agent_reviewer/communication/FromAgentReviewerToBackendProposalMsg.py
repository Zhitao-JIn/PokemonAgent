"""`FromAgentReviewerToBackendProposalMsg`：跳 C（agent → 后端）推一笔结论。无回话。

agent 把 `seed`/`turn` 的结果包成这封推回后端；后端转成跳 B `ProposalReq` 广播给网页。
`round`：0 为首轮，每轮 `turn` 后 +1（与跳 B `ProposalReq.round` 对齐）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from pokemon_agent.schemas.review_backend.communication.ProposedAnswer import ProposedAnswer


class FromAgentReviewerToBackendProposalMsg(BaseModel):
    """一笔 AI 复核席的结论，从 agent 进程推回后端。"""

    msg: Literal["proposal"] = Field(default="proposal", description="消息标签：后端据此分流")
    seq: int = Field(ge=1, description="这一笔结论对应第几问（与跳 B 同号）")
    proposal: ProposedAnswer = Field(description="AI 给的结论草案")
    round: int = Field(default=0, ge=0, description="讨论轮次：0 为首轮，每轮 turn +1")


# 兼容类型别名。
ProposalMsg = FromAgentReviewerToBackendProposalMsg

__all__ = ["FromAgentReviewerToBackendProposalMsg", "ProposalMsg", "ProposedAnswer"]
