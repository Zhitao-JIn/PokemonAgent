"""共用重问图的用法：AI 连续上限、人的无限轮次、清零及到顶原话落账。"""

import json
from pathlib import Path
from typing import Literal

import pytest
from _review_context import review_context
from pydantic import BaseModel

from pokemon_agent.direct.trace import TraceTool
from pokemon_agent.harness.reviewing import ReviewRound, ask_inject, elicit_with_review
from pokemon_agent.schemas.harness import (
    FromHarnessToReviewerInjectReq,
    FromHarnessToReviewerInjectResp,
)
from pokemon_agent.schemas.harness.domain import ReviewMark

ReplyBy = Literal["human", "agent", "none"]


class Draft(BaseModel):
    number: int
    note: str


class ScriptedReviewer:
    def __init__(self, replies: list[tuple[ReplyBy, str]]) -> None:
        self.replies = list(replies)
        self.requests: list[FromHarnessToReviewerInjectReq] = []

    def inject(self, req: FromHarnessToReviewerInjectReq) -> FromHarnessToReviewerInjectResp:
        self.requests.append(req)
        assert self.replies, "review loop asked beyond its script"
        by, text = self.replies.pop(0)
        return FromHarnessToReviewerInjectResp(text=text, by=by, answered=by != "none")


def _exercise(
    root: Path, replies: list[tuple[ReplyBy, str]], limit: int
) -> tuple[Draft, str, list[str], list[dict], ScriptedReviewer]:
    reviewer = ScriptedReviewer(replies)
    trace = TraceTool.build(run_id="r1", trace_root=root)
    notes: list[str] = []

    def ask_brain(note: str, number: int) -> Draft:
        notes.append(note)
        return Draft(number=number, note=note)

    def ask_reviewer(draft: Draft, rounds: ReviewRound) -> ReviewMark:
        req = FromHarnessToReviewerInjectReq(
            prompt="复核提案",
            form=draft,
            form_kind="Draft",
            context=review_context(),
            round=rounds.number,
            max_agent_rounds=rounds.max_agent_rounds,
        )
        return ask_inject(
            reviewer,
            trace,
            req,
            rounds=rounds,
            meta={"source": "plan_run", "episode_id": "r1", "task_id": "r1", "step": 0},
        )

    draft, note = elicit_with_review(ask_brain, ask_reviewer, max_agent_rounds=limit)
    events = [json.loads(event.content) for event in trace.read_events({"run_id": "r1"})]
    return draft, note, notes, events, reviewer


def test_inject_loop_caps_agent_rounds_not_human(tmp_path: Path) -> None:
    replies: list[tuple[ReplyBy, str]] = [("agent", "A"), ("agent", "B"), ("agent", "不得生效")]

    draft, note, inputs, events, reviewer = _exercise(tmp_path, replies, limit=2)

    assert inputs == ["", "A", "B"]
    assert draft.number == 3 and draft.note == note == "B"
    assert [e["capped"] for e in events] == ["false", "false", "true"]
    assert events[-1]["reply"] == "不得生效" and events[-1]["by"] == "agent"
    assert [e["round"] for e in events] == ["1", "2", "3"]
    assert [req.round for req in reviewer.requests] == [1, 2, 3]
    assert all(req.max_agent_rounds == 2 for req in reviewer.requests)


def test_humans_have_no_round_cap_and_reset_the_agent_streak(tmp_path: Path) -> None:
    replies: list[tuple[ReplyBy, str]] = [("human", f"H{i}") for i in range(15)]
    replies += [("agent", "A1"), ("agent", "A2"), ("human", "重置")]
    replies += [("agent", "B1"), ("agent", "B2"), ("agent", "不得生效")]

    draft, note, inputs, events, reviewer = _exercise(tmp_path, replies, limit=2)

    assert len(inputs) == len(replies) == 21
    assert draft.note == note == "B2"
    assert inputs[-3:] == ["重置", "B1", "B2"]
    assert [e["capped"] for e in events] == ["false"] * 20 + ["true"]
    assert [req.round for req in reviewer.requests] == list(range(1, 22))


@pytest.mark.parametrize(
    "replies, limit, inputs, capped",
    [
        ([("agent", "A"), ("agent", "")], 1, ["", "A"], ["false", "false"]),
        ([("agent", "不得生效")], 0, [""], ["true"]),
        ([("none", "")], 0, [""], ["false"]),
        ([("human", "H"), ("human", "")], 0, ["", "H"], ["false", "false"]),
    ],
)
def test_zero_limit_and_empty_replies_finish_without_extra_brain_calls(
    tmp_path: Path,
    replies: list[tuple[ReplyBy, str]],
    limit: int,
    inputs: list[str],
    capped: list[str],
) -> None:
    draft, note, actual_inputs, events, _ = _exercise(tmp_path, replies, limit)

    assert actual_inputs == inputs
    assert draft.note == note == inputs[-1]
    assert [e["capped"] for e in events] == capped


def test_agent_streak_is_local_to_one_elicitation(tmp_path: Path) -> None:
    for index in (1, 2):
        _, note, inputs, events, _ = _exercise(
            tmp_path / str(index), [("agent", "A"), ("agent", "B")], limit=1
        )

        assert inputs == ["", "A"] and note == "A"
        assert [event["round"] for event in events] == ["1", "2"]
