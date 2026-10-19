"""brain_goal_judge v2 冻结契约。"""

import hashlib
import json

import pytest

from evals.dataset.brain_goal_judge.build.freeze_v2 import build_cases
from evals.dataset.brain_goal_judge.loader import load


def _row(base_request: dict, event_uuid: str, truth_method: str) -> dict:
    history = base_request["history"]
    request = {**base_request, "history": history}
    return {
        "candidate_id": f"candidate-{event_uuid}",
        "event_uuid": event_uuid,
        "run_id": "run-1",
        "episode_id": "episode-1",
        "task_id": f"task-{event_uuid}",
        "step": 1,
        "goal_family": "navigation",
        "criteria": "where 显示 x=9 y=14",
        "request": request,
        "request_sha256": hashlib.sha256(
            json.dumps(request, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
        "prompt_exact": True,
        "image_bound": True,
        "truth_method": truth_method,
        "achieved": True if truth_method == "mechanical" else None,
        "negative_mode": None,
        "check_id": "reach_map12_y14" if truth_method == "mechanical" else None,
        "suggested_achieved": None,
        "evidence": [{"source": "trace", "locator": "trace/event.json", "summary": "机械证据"}]
        if truth_method == "mechanical"
        else [],
    }


def test_v2_build_marks_rule_based_history_adjudication_separately() -> None:
    request = load()[0].request.model_dump(mode="json")
    cases = build_cases(
        [
            _row(request, "mechanical-event", "mechanical"),
            _row(request, "adjudicated-event", "history_adjudicated"),
        ]
    )

    mechanical, adjudicated = cases

    assert mechanical.case_id == "mechanical-event"
    assert mechanical.truth_method == "mechanical"
    assert adjudicated.case_id == "adjudicated-event"
    assert adjudicated.truth_method == "history_adjudicated"
    assert adjudicated.achieved is True
    assert adjudicated.evidence[0].source == "request_history"
    assert "request.history" in adjudicated.evidence[0].locator


def test_v2_build_rejects_duplicate_event_ids() -> None:
    request = load()[0].request.model_dump(mode="json")
    row = _row(request, "duplicate", "mechanical")

    with pytest.raises(ValueError, match="duplicate judge event UUID"):
        build_cases([row, row])


def test_frozen_v2_is_hash_verified_and_keeps_complete_history() -> None:
    cases = load("v2")

    assert len(cases) == 257
    assert len({case.case_id for case in cases}) == len(cases)
    assert sum(case.truth_method == "mechanical" for case in cases) == 145
    assert sum(case.truth_method == "history_adjudicated" for case in cases) == 112
    assert sum(case.truth_method == "human" for case in cases) == 0
    assert (
        sum(
            1
            for case in cases
            for memory in case.request.history
            if memory.before_frame and memory.after_frame
        )
        == 1063
    )
    assert all(case.origin.trace_uuid == case.case_id for case in cases)
    assert all(case.evidence for case in cases)
