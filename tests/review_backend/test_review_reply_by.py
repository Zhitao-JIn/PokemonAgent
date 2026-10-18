"""跳 A 回话映射的用法示范；内部了结标签与对外来源标签分别保留语义。"""

import pytest

from pokemon_agent.review_backend.backend import _settle, _to_resp
from pokemon_agent.schemas.review_backend import (
    FromFrontendToReviewBackendAnswerReq,
    FromReviewBackendToFrontendAskReq,
)


@pytest.mark.parametrize("kind", ["inject", "audit"])
@pytest.mark.parametrize("by", ["human", "agent", "timeout", "harness_gone"])
def test_backend_reply_maps_settlement_to_who_answered(kind: str, by: str) -> None:
    """两种问答保留 human/agent，超时与源程序断连对外统一为 none。"""
    ask = FromReviewBackendToFrontendAskReq(seq=1, run_id="r1", kind=kind, prompt="p", body="b")
    answer = (
        FromFrontendToReviewBackendAnswerReq(seq=1, by=by, text="意见", verdict="accept")
        if by in {"human", "agent"}
        else None
    )

    settle = _settle(ask, answer, by)
    reply = _to_resp(settle)

    expected = by if by in {"human", "agent"} else "none"
    assert settle.by == by
    assert reply.by == expected
    assert reply.answered == (expected != "none")
