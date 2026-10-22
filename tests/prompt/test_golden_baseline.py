"""Check the frozen corpus inventory; gateway replay lives in the migrated baseline tests."""

from pathlib import Path

GOLDEN = Path(__file__).parent / "golden"
REQUESTS = sorted(GOLDEN.glob("*/*.req.json"))


def test_golden_inventory_is_present() -> None:
    assert REQUESTS, "The checked-in frozen corpus must be present"
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
