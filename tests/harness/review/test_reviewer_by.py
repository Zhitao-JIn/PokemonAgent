"""复核席回话来源的用法示范：三种实现、回话不变式与落盘账。"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Literal

import pytest
from _fake_run import build_fake
from pydantic import ValidationError

from pokemon_agent.harness.console_reviewer import ConsoleReviewer
from pokemon_agent.harness.interface.reviewer import Reviewer
from pokemon_agent.harness.null_reviewer import NullReviewer
from pokemon_agent.harness.reviewing import ask_inject, audit_judgement
from pokemon_agent.harness.web_reviewer import WebReviewer
from pokemon_agent.schemas.harness import (
    AuditVerdict,
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToReviewBackendAuditResp,
    FromHarnessToReviewBackendInjectResp,
    FromHarnessToReviewerAuditReq,
    FromHarnessToReviewerAuditResp,
    FromHarnessToReviewerInjectReq,
    FromHarnessToReviewerInjectResp,
    ModelCall,
)

ReplyBy = Literal["human", "agent", "none"]


class _Connection:
    """脚本化连接：按顺序回 JSON 或断连，不创建套接字。"""

    def __init__(self, replies: list[str | OSError]) -> None:
        self.replies = replies
        self.sent: list[str] = []
        self.closed = False

    def send(self, data: str) -> None:
        self.sent.append(data)

    def recv(self, timeout: float | None = None) -> str:
        reply = self.replies.pop(0)
        if isinstance(reply, OSError):
            raise reply
        return reply

    def close(self) -> None:
        self.closed = True


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
            FromHarnessToReviewerInjectReq(prompt="意见", form={}, form_kind="x")
        )
    return reviewer.audit(
        FromHarnessToReviewerAuditReq(
            run_id="r1",
            episode_id="r1-ep1",
            outcome=FromHarnessToBrainToolJudgeResp(done=True, why="依据", calls=[ModelCall()]),
        )
    )


def _check_reply(
    response: FromHarnessToReviewerInjectResp | FromHarnessToReviewerAuditResp, expected: ReplyBy
) -> None:
    assert response.by == expected
    assert response.answered == (response.by != "none")


@pytest.mark.parametrize("kind", ["inject", "audit"])
def test_by_and_answered_invariant(monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    """三种复核席标明来源，Web 断连后每问默认；四种信封拒绝不一致与缺失标签。"""
    backend_type = (
        FromHarnessToReviewBackendInjectResp
        if kind == "inject"
        else FromHarnessToReviewBackendAuditResp
    )
    replies = [
        backend_type(
            seq=index, text="", verdict=AuditVerdict.ACCEPT, answered=by != "none", by=by
        ).model_dump_json()
        for index, by in enumerate(("human", "agent", "none"), 1)
    ]
    connection = _Connection([*replies, OSError("后端断连")])
    monkeypatch.setattr("pokemon_agent.harness.web_reviewer.connect", lambda *a, **k: connection)

    _check_reply(_reply(NullReviewer(), kind), "none")
    monkeypatch.setattr("sys.stdin", io.StringIO("\n"))
    _check_reply(_reply(ConsoleReviewer(timeout=0), kind), "human")
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    _check_reply(_reply(ConsoleReviewer(timeout=0), kind), "none")
    web = WebReviewer("r1", "ws://fake.invalid", timeout=0)
    try:
        for expected in ("human", "agent", "none", "none", "none"):
            _check_reply(_reply(web, kind), expected)
    finally:
        web.close()

    assert connection.closed
    assert len(connection.sent) == 4
    _check_invalid_replies()


def _check_invalid_replies() -> None:
    """四种信封都拒绝矛盾或缺失的来源标签。"""
    for model in (
        FromHarnessToReviewerInjectResp,
        FromHarnessToReviewerAuditResp,
        FromHarnessToReviewBackendInjectResp,
        FromHarnessToReviewBackendAuditResp,
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
    request = FromHarnessToReviewerInjectReq(prompt="意见", form={}, form_kind="x")
    verdict = FromHarnessToBrainToolJudgeResp(done=True, why="依据", calls=[ModelCall()])

    ask_inject(reviewer, trace, request, meta=meta)
    audit_judgement(reviewer, trace, verdict, run_id="r1", meta=meta)

    events = trace.read_events({"run_id": "r1"})
    assert {event.kind for event in events} == {"review_inject", "review_audit"}
    for event in events:
        content = json.loads(event.content)
        assert content["by"] == by
        assert content["answered"] == str(by != "none").lower()
