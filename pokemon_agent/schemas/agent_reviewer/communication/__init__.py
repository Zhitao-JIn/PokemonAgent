"""`schemas/agent_reviewer/communication` 包统一出口：跳 C（后端 ↔ agent 进程）的信封。

agent 是独立进程，后端是 WS 客户端、agent 是 WS 服务端。四件信封按 `msg` 分流，与跳 A/跳 B 同构。
`ProposedAnswer` / `AskReq` / `ChatTurn` 直接复用既有模型，不新造——`ProposedAnswer` 的定义在
`schemas/review_backend/communication/ProposedAnswer.py`，本包只 import 复用。
"""

from __future__ import annotations

from .ChatTurn import ChatTurn
from .FromAgentReviewerToBackendProposalMsg import (
    FromAgentReviewerToBackendProposalMsg,
    ProposalMsg,
)
from .FromBackendToAgentReviewerCloseReq import (
    CloseReq,
    FromBackendToAgentReviewerCloseReq,
)
from .FromBackendToAgentReviewerSeedReq import (
    FromBackendToAgentReviewerSeedReq,
    SeedReq,
)
from .FromBackendToAgentReviewerTurnReq import (
    FromBackendToAgentReviewerTurnReq,
    TurnReq,
)

MSG_SEED = "seed"
MSG_TURN = "turn"
MSG_CLOSE = "close"
MSG_PROPOSAL = "proposal"
"""跳 C 的四类 `msg` 标签（与各信封类的 `msg` 字段一致，供 agent server / 客户端分流用）。"""

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
