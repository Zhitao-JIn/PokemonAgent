"""真实四个审点传递当次请求原对象，重问带上上一轮意见，计数对齐 trace。"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from _fake_run import GOAL, build_fake, every
from pydantic import BaseModel

from pokemon_agent.direct.brain_tool import Decomposer, Judger, Planner
from pokemon_agent.schemas.harness import (
    AuditVerdict,
    FromHarnessToBrainToolDecomposeReq,
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToBrainToolPlanOnceReq,
    FromHarnessToReviewerAuditReq,
    FromHarnessToReviewerAuditResp,
    FromHarnessToReviewerInjectReq,
    FromHarnessToReviewerInjectResp,
)
from pokemon_agent.schemas.harness.domain import EntryStatus
from pokemon_agent.schemas.harness.domain.review_context import BrainInput


class CapturingReviewer:
    """每层首次规划给一句意见，随后接受；判成一律认账。"""

    def __init__(self) -> None:
        self.requests: list[FromHarnessToReviewerInjectReq | FromHarnessToReviewerAuditReq] = []

    def inject(self, req: FromHarnessToReviewerInjectReq) -> FromHarnessToReviewerInjectResp:
        prior = [
            r
            for r in self.requests
            if isinstance(r, FromHarnessToReviewerInjectReq)
            and r.context.layer == req.context.layer
        ]
        self.requests.append(req)
        return FromHarnessToReviewerInjectResp(
            text="重看路线" if not prior else "", answered=True, by="human"
        )

    def audit(self, req: FromHarnessToReviewerAuditReq) -> FromHarnessToReviewerAuditResp:
        self.requests.append(req)
        return FromHarnessToReviewerAuditResp(
            verdict=AuditVerdict.ACCEPT, answered=True, by="human"
        )


def _capture(
    original: Callable[..., BaseModel], inputs: list[BrainInput]
) -> Callable[..., BaseModel]:
    def call(port: object, req: BrainInput) -> BaseModel:
        inputs.append(req)
        return original(port, req)

    return call


def test_four_review_points_carry_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reviewer = CapturingReviewer()
    inputs: list[BrainInput] = []
    for port, method in ((Planner, "plan"), (Decomposer, "decompose"), (Judger, "judge")):
        monkeypatch.setattr(port, method, _capture(getattr(port, method), inputs))
    fake = build_fake(tmp_path, reviewer=reviewer, episode=every(1), run=every(1))

    fake.harness.run("r1", [GOAL])

    events = [
        e
        for e in fake.trace.read_events({"run_id": "r1"})
        if e.kind in {"review_inject", "review_audit"}
    ]
    assert len(events) == len(reviewer.requests)
    points: set[tuple[str, type]] = set()
    for request, event in zip(reviewer.requests, events, strict=True):
        ctx, meta = request.context, json.loads(event.meta)
        assert any(ctx.brain_input is req for req in inputs)
        assert ctx.run_id == "r1" and ctx.episode_id == meta["episode_id"]
        assert ctx.step == meta["step"] and ctx.fail_streak == 0
        points.add((ctx.layer, type(ctx.brain_input)))
        if isinstance(request, FromHarnessToReviewerAuditReq):
            table = ctx.goals if ctx.layer == "run" else ctx.tasks
            assert any(e.status is EntryStatus.COMPLETED for e in table)
            assert all(e.status is not EntryStatus.RUNNING for e in table)
    assert points == {
        ("run", FromHarnessToBrainToolPlanOnceReq),
        ("run", FromHarnessToBrainToolJudgeReq),
        ("episode", FromHarnessToBrainToolDecomposeReq),
        ("episode", FromHarnessToBrainToolJudgeReq),
    }
    for layer in ("run", "episode"):
        planning = [
            r.context.brain_input
            for r in reviewer.requests
            if isinstance(r, FromHarnessToReviewerInjectReq) and r.context.layer == layer
        ]
        assert [req.human_note for req in planning[:2]] == ["", "重看路线"]
    assert [r.context.step for r in reviewer.requests[:2]] == [0, 0]
