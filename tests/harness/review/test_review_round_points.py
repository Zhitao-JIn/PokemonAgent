"""真实 run/episode 图均按同一上限重问，并保留被截的原话与最终生效意见。"""

import json
from pathlib import Path

import pytest
from _fake_run import GOAL, build_fake, every
from _harness_fixtures.app_config import reconfigure

from pokemon_agent.schemas.harness import (
    AuditVerdict,
    FromHarnessToReviewerAuditReq,
    FromHarnessToReviewerAuditResp,
    FromHarnessToReviewerInjectReq,
    FromHarnessToReviewerInjectResp,
)


class AgentReviewer:
    def __init__(self, layer: str) -> None:
        self.layer = layer
        self.requests: list[FromHarnessToReviewerInjectReq] = []

    def inject(self, req: FromHarnessToReviewerInjectReq) -> FromHarnessToReviewerInjectResp:
        if req.context.layer != self.layer:
            return FromHarnessToReviewerInjectResp(text="", answered=False, by="none")
        self.requests.append(req)
        assert len(self.requests) <= 4, "fifth agent reply must never be requested"
        return FromHarnessToReviewerInjectResp(
            text=f"A{len(self.requests)}", answered=True, by="agent"
        )

    def audit(self, req: FromHarnessToReviewerAuditReq) -> FromHarnessToReviewerAuditResp:
        return FromHarnessToReviewerAuditResp(
            verdict=AuditVerdict.ACCEPT, answered=False, by="none"
        )


@pytest.mark.parametrize(
    "layer, verdict_kind", [("run", "plan_verdict"), ("episode", "decompose_verdict")]
)
def test_both_planning_graphs_apply_three_agent_replies_and_keep_the_fourth_on_the_books(
    tmp_path: Path, layer: str, verdict_kind: str
) -> None:
    reviewer = AgentReviewer(layer)
    fake = build_fake(tmp_path, reviewer=reviewer, task=every(1), episode=every(1), run=every(1))
    reconfigure(fake.run_rt, budget={"max_decompositions": 20})

    fake.harness.run("r1", [GOAL])

    assert [req.context.brain_input.human_note for req in reviewer.requests] == [
        "",
        "A1",
        "A2",
        "A3",
    ]
    assert [req.round for req in reviewer.requests] == [1, 2, 3, 4]
    assert all(req.max_agent_rounds == 3 for req in reviewer.requests)
    events = fake.trace.read_events({"run_id": "r1", "source": f"plan_{layer}"})
    marks = [json.loads(event.content) for event in events if event.kind == "review_inject"]
    assert [mark["capped"] for mark in marks] == ["false", "false", "false", "true"]
    assert [mark["round"] for mark in marks] == ["1", "2", "3", "4"]
    assert marks[-1]["reply"] == "A4"
    verdicts = [json.loads(event.content) for event in events if event.kind == verdict_kind]
    assert len(verdicts) == 1 and verdicts[0]["human_note"] == "A3"
