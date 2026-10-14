"""A1 信封：构造、JSON 往返、`msg` 标签、`by`/`deadline` 取值。

覆盖：跳 B 三处改动（AskReq.deadline→float|None、SettleReq.by 加 agent、AnswerReq.by）
+ 新增 ProposalReq/DiscussReq/ProposedAnswer + 跳 C 四件信封
+ （SeedReq/TurnReq/CloseReq/ProposalMsg）+ ChatTurn。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pokemon_agent.schemas.agent_reviewer import (
    MSG_CLOSE,
    MSG_PROPOSAL,
    MSG_SEED,
    MSG_TURN,
    ChatTurn,
    CloseReq,
    ProposalMsg,
    SeedReq,
    TurnReq,
)
from pokemon_agent.schemas.review_backend import (
    FromFrontendToReviewBackendAnswerReq,
    FromFrontendToReviewBackendDiscussReq,
    FromReviewBackendToFrontendAskReq,
    FromReviewBackendToFrontendProposalReq,
    FromReviewBackendToFrontendSettleReq,
    ProposedAnswer,
)


def test_ask_deadline_accepts_none_and_float() -> None:
    ask_none = FromReviewBackendToFrontendAskReq(
        seq=1, run_id="r", kind="inject", prompt="p", body="b", deadline=None
    )
    assert ask_none.deadline is None
    raw = ask_none.model_dump_json()
    assert FromReviewBackendToFrontendAskReq.model_validate_json(raw).deadline is None

    ask_t = FromReviewBackendToFrontendAskReq(
        seq=2, run_id="r", kind="audit", prompt="p", body="b", deadline=123.0
    )
    assert ask_t.deadline == 123.0


def test_settle_by_includes_agent() -> None:
    assert FromReviewBackendToFrontendSettleReq(seq=1, by="agent").by == "agent"
    assert FromReviewBackendToFrontendSettleReq(seq=1, by="human").by == "human"
    # 旧取值不受影响
    assert FromReviewBackendToFrontendSettleReq(seq=1, by="timeout").by == "timeout"
    assert FromReviewBackendToFrontendSettleReq(seq=1, by="harness_gone").by == "harness_gone"
    with pytest.raises(ValidationError):
        FromReviewBackendToFrontendSettleReq(seq=1, by="bogus")  # type: ignore[arg-type]


def test_answer_by_default_human_and_explicit() -> None:
    assert FromFrontendToReviewBackendAnswerReq(seq=1, verdict="accept").by == "human"
    assert FromFrontendToReviewBackendAnswerReq(seq=1, by="agent", text="x").by == "agent"


def test_proposed_answer_shape_and_roundtrip() -> None:
    pa = ProposedAnswer(text="看清楚了", verdict="accept", note="")
    raw = pa.model_dump_json()
    assert ProposedAnswer.model_validate_json(raw) == pa


def test_proposal_req_msg_and_fields() -> None:
    pr = FromReviewBackendToFrontendProposalReq(seq=3, proposal=ProposedAnswer(text="ok"), round=1)
    assert pr.msg == "proposal"
    assert pr.round == 1
    assert FromReviewBackendToFrontendProposalReq.model_validate_json(pr.model_dump_json()) == pr


def test_discuss_req_msg_and_fields() -> None:
    d = FromFrontendToReviewBackendDiscussReq(seq=3, text="再想想")
    assert d.msg == "discuss"
    assert d.text == "再想想"
    assert FromFrontendToReviewBackendDiscussReq.model_validate_json(d.model_dump_json()) == d


def test_jump_c_envelopes_msg_and_roundtrip() -> None:
    ask = FromReviewBackendToFrontendAskReq(
        seq=1, run_id="r", kind="inject", prompt="p", body="b", deadline=None
    )
    seed = SeedReq(seq=1, ask=ask, frame="data:image/png;base64,AAA")
    assert seed.msg == MSG_SEED and seed.seq == 1 and seed.frame.startswith("data:image")
    assert SeedReq.model_validate_json(seed.model_dump_json()) == seed

    turn = TurnReq(seq=1, delta=ChatTurn(role="human", text="改一下"), frame=None)
    assert turn.msg == MSG_TURN and turn.delta.role == "human"
    assert TurnReq.model_validate_json(turn.model_dump_json()) == turn

    close = CloseReq(seq=1)
    assert close.msg == MSG_CLOSE
    assert CloseReq.model_validate_json(close.model_dump_json()) == close

    pm = ProposalMsg(seq=1, proposal=ProposedAnswer(text="结论"), round=0)
    assert pm.msg == MSG_PROPOSAL and pm.round == 0
    assert ProposalMsg.model_validate_json(pm.model_dump_json()) == pm


def test_chat_turn_roles() -> None:
    for role in ("system", "human", "agent"):
        assert ChatTurn(role=role, text="x").role == role  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ChatTurn(role="bogus", text="x")  # type: ignore[arg-type]
