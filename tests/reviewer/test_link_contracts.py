"""线上类型校验、请求身份与 run 侧导入边界。"""

import ast
import json
from pathlib import Path

import pytest
from _doubles.reviewer import audit_request, inject_request
from pydantic import ValidationError

from pokemon_agent import reviewer_link
from pokemon_agent.reviewer_link import RemoteReviewer
from pokemon_agent.schemas.harness import (
    FromHarnessToReviewerAskMsg,
    FromHarnessToReviewerCancelMsg,
)
from pokemon_agent.schemas.reviewer.communication import FromReviewerToHarnessHelloMsg


@pytest.mark.parametrize(
    "req, op", [(inject_request(frames=True), "inject"), (audit_request(), "audit")]
)
def test_wire_serialization_preserves_the_entire_question_snapshot(req, op: str) -> None:
    wire = FromHarnessToReviewerAskMsg(qid="stable", op=op, req=req)

    copied = FromHarnessToReviewerAskMsg.model_validate_json(wire.model_dump_json())

    assert copied.model_dump(mode="json") == wire.model_dump(mode="json")
    assert copied.qid == "stable"


@pytest.mark.parametrize("change", [{"qid": ""}, {"op": "audit"}, {"msg": "unknown"}, {"extra": 1}])
def test_invalid_wire_fields_are_explicit_validation_errors(change: dict) -> None:
    data = FromHarnessToReviewerAskMsg(qid="x", op="inject", req=inject_request()).model_dump(
        mode="json"
    )
    data.update(change)

    with pytest.raises(ValidationError):
        FromHarnessToReviewerAskMsg.model_validate_json(json.dumps(data))


def test_cancel_and_hello_tags_are_not_ambiguous() -> None:
    assert FromHarnessToReviewerCancelMsg(qid="x").msg == "cancel"
    with pytest.raises(ValidationError):
        FromReviewerToHarnessHelloMsg(mode="unknown")


@pytest.mark.parametrize(
    "url, budget",
    [
        ("http://localhost", 1),
        ("ws://", 1),
        ("ws://localhost:0", 1),
        ("ws://localhost:abc", 1),
        ("ws://localhost:8765", -1),
    ],
)
def test_invalid_connection_configuration_fails_before_starting_a_background_thread(
    url: str, budget: float
) -> None:
    with pytest.raises(ValueError):
        RemoteReviewer(url, flush=lambda: None, lost_timeout_s=budget)


def test_run_side_link_imports_no_reviewer_or_harness_implementation() -> None:
    for source in Path(reviewer_link.__file__).parent.rglob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                names = [node.module or ""]
            else:
                continue
            assert all(
                not name.startswith("pokemon_agent.") or name.startswith("pokemon_agent.schemas.")
                for name in names
            ), source
