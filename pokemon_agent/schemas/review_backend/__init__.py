"""`schemas/review_backend` 包统一出口：跳 B（后端 ↔ 网页）的信封。

网页是 JS，这几封唯一的 Python 消费者是 `pokemon_agent/review_backend/`，所以跟后端住一处
（`docs/web_reviewer/spec.md` §3.2）。跳 A（源程序 ↔ 后端）的信封由 harness 发起，
在 `schemas/harness/`。每条消息带 `msg` 标签，同一条 WebSocket 上据此分流。

只做 re-export、不定义任何实体。
"""

from __future__ import annotations

from .communication.FromFrontendToReviewBackendAnswerReq import (
    FromFrontendToReviewBackendAnswerReq,
)
from .communication.FromFrontendToReviewBackendAnswerResp import (
    FromFrontendToReviewBackendAnswerResp,
)
from .communication.FromReviewBackendToFrontendAskReq import FromReviewBackendToFrontendAskReq
from .communication.FromReviewBackendToFrontendFeedReq import FromReviewBackendToFrontendFeedReq
from .communication.FromReviewBackendToFrontendSettleReq import (
    FromReviewBackendToFrontendSettleReq,
)

__all__ = [
    "FromFrontendToReviewBackendAnswerReq",
    "FromFrontendToReviewBackendAnswerResp",
    "FromReviewBackendToFrontendAskReq",
    "FromReviewBackendToFrontendFeedReq",
    "FromReviewBackendToFrontendSettleReq",
]
