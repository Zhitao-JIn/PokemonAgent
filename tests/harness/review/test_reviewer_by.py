"""复核席回话来源的用法示范：回话不变式与落盘账。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import pytest
from _fake_run import build_fake
from _review_context import review_context
from pydantic import ValidationError

from pokemon_agent.harness.interface.reviewer import Reviewer
from pokemon_agent.harness.null_reviewer import NullReviewer
from pokemon_agent.harness.reviewing import ReviewRound, ask_inject, audit_judgement
from pokemon_agent.schemas.harness import (
    AuditVerdict,
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToReviewerAuditReq,
    FromHarnessToReviewerAuditResp,
    FromHarnessToReviewerInjectReq,
    FromHarnessToReviewerInjectResp,
    ModelCall,
)

ReplyBy = Literal["human", "agent", "none"]


class _TaggedReviewer:
    """用来源标签注入一份确定的回话。"""

    def __init__(self, by: ReplyBy) -> None:
        self.by = by

    def inject(self, req: FromHarnessToReviewerInjectReq) -> FromHarnessToReviewerInjectResp:
        return FromHarnessToReviewerInjectResp(text="", answered=self.by != "none", by=self.by)

    def audit(self, req: FromHarnessToReviewerAuditReq) -> FromHarnessToReviewerAuditResp:
        return FromHarnessToReviewerAuditResp(
            verdict=AuditVerdict.ACCEPT, answered=self.by != "none", by=self.by
        )


def _reply(
    reviewer: Reviewer, kind: str
) -> FromHarnessToReviewerInjectResp | FromHarnessToReviewerAuditResp:
    if kind == "inject":
        return reviewer.inject(
            FromHarnessToReviewerInjectReq(
                prompt="意见", form={}, form_kind="x", context=review_context()
            )
        )
    return reviewer.audit(
        FromHarnessToReviewerAuditReq(
            run_id="r1",
            episode_id="r1-ep1",
            outcome=FromHarnessToBrainToolJudgeResp(done=True, why="依据", calls=[ModelCall()]),
            context=review_context(),
        )
    )


def _check_reply(
    response: FromHarnessToReviewerInjectResp | FromHarnessToReviewerAuditResp, expected: ReplyBy
) -> None:
    assert response.by == expected
    assert response.answered == (response.by != "none")


@pytest.mark.parametrize("kind", ["inject", "audit"])
def test_by_and_answered_invariant(kind: str) -> None:
    """空复核席标记未回答，两种响应拒绝矛盾或缺失的来源标签。"""
    _check_reply(_reply(NullReviewer(), kind), "none")
    for by in ("human", "agent", "none"):
        _check_reply(_reply(_TaggedReviewer(by), kind), by)
    _check_invalid_replies()


def _check_invalid_replies() -> None:
    """两种信封都拒绝矛盾或缺失的来源标签。"""
    for model in (
        FromHarnessToReviewerInjectResp,
        FromHarnessToReviewerAuditResp,
    ):
        for by, answered in (("none", True), ("human", False)):
            with pytest.raises(ValidationError, match="answered must equal"):
                model.model_validate(
                    {"seq": 1, "verdict": "accept", "text": "", "answered": answered, "by": by}
                )
        with pytest.raises(ValidationError, match="by"):
            model.model_validate({"seq": 1, "verdict": "accept", "text": "", "answered": False})


@pytest.mark.parametrize("by", ["human", "agent", "none"])
def test_review_accounts_record_who_answered(tmp_path: Path, by: ReplyBy) -> None:
    """来源从复核席回话经 ReviewMark 写进两本账的 content。"""
    reviewer = _TaggedReviewer(by)
    trace = build_fake(tmp_path).trace
    meta = {"source": "review_and_judge", "episode_id": "r1-ep1", "task_id": "", "step": 1}
    rounds = ReviewRound(number=1, consecutive_agent_rounds=0, max_agent_rounds=3)
    request = FromHarnessToReviewerInjectReq(
        prompt="意见",
        form={},
        form_kind="x",
        context=review_context(),
        round=rounds.number,
        max_agent_rounds=rounds.max_agent_rounds,
    )
    verdict = FromHarnessToBrainToolJudgeResp(done=True, why="依据", calls=[ModelCall()])

    ask_inject(reviewer, trace, request, meta=meta, rounds=rounds)
    audit_judgement(reviewer, trace, verdict, run_id="r1", meta=meta, context=review_context())

    events = trace.read_events({"run_id": "r1"})
    assert {event.kind for event in events} == {"review_inject", "review_audit"}
    for event in events:
        content = json.loads(event.content)
        assert content["by"] == by
        assert content["answered"] == str(by != "none").lower()
