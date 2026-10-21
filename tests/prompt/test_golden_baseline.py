"""Replay each captured request against the unchanged pre-migration builders."""

from pathlib import Path

import pytest

from scripts.capture_prompt_golden import GoldenCase, render_case

GOLDEN = Path(__file__).parent / "golden"
REQUESTS = sorted(GOLDEN.glob("*/*.req.json"))


def test_golden_inventory_is_present() -> None:
    assert REQUESTS, "Run scripts/capture_prompt_golden.py first"
    assert {path.parent.name for path in REQUESTS} == {
        "decide_action",
        "judge_success",
        "decompose",
        "run_plan",
        "verify",
        "summarize",
        "summarize_task",
        "summarize_run",
        "retry_prompt",
    }
    assert sum(path.stat().st_size for path in GOLDEN.rglob("*") if path.is_file()) <= 5_000_000
    assert len(list(GOLDEN.glob("*/*.prompt.txt"))) == len(REQUESTS)


@pytest.mark.parametrize("request_path", REQUESTS, ids=lambda path: str(path.relative_to(GOLDEN)))
def test_golden_baseline(request_path: Path) -> None:
    case = GoldenCase.model_validate_json(request_path.read_bytes())
    expected_path = request_path.with_name(
        request_path.name.removesuffix(".req.json") + ".prompt.txt"
    )

    actual = render_case(case)

    assert actual == expected_path.read_bytes()
