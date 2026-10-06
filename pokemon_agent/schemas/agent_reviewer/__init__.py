"""`schemas/agent_reviewer` 包统一出口：跳 C（后端 ↔ agent 进程）的信封与协议常量。"""

from __future__ import annotations

from .communication import (
    ChatTurn,
    CloseReq,
    FromAgentReviewerToBackendProposalMsg,
    FromBackendToAgentReviewerCloseReq,
    FromBackendToAgentReviewerSeedReq,
    FromBackendToAgentReviewerTurnReq,
    ProposalMsg,
    SeedReq,
    TurnReq,
)

MSG_SEED = "seed"
MSG_TURN = "turn"
MSG_CLOSE = "close"
MSG_PROPOSAL = "proposal"
"""跳 C 的四类 `msg` 标签（与信封类的 `msg` 字段一致，供 agent server 分流用）。"""

__all__ = [
    "ChatTurn",
    "CloseReq",
    "FromAgentReviewerToBackendProposalMsg",
    "FromBackendToAgentReviewerCloseReq",
    "FromBackendToAgentReviewerSeedReq",
    "FromBackendToAgentReviewerTurnReq",
    "MSG_CLOSE",
    "MSG_PROPOSAL",
    "MSG_SEED",
    "MSG_TURN",
    "ProposalMsg",
    "SeedReq",
    "TurnReq",
]
