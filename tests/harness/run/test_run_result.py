"""`RunResult`（V8，plan2 R1）的用法示范：契约往返、账聚合口径、假 run 全链带回。

聚合的假账搭法与 `test_evals_checks` 同源（手工 ParsedEvent）；全链用 `_fake_run`
的真三张图——usage 从假 run 的 `_call` 账聚合出来，这就是"eval 不再读 trace"的兑现。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _fake_run import GOAL, build_fake

from pokemon_agent.direct.trace import ParsedEvent
from pokemon_agent.direct.trace.content import (
    CallExhaustedContent,
    CallFailedContent,
    EpisodeEndContent,
    EpisodeStartContent,
    EventMeta,
    ModelCallContent,
)
from pokemon_agent.harness.run.run_result import aggregate
from pokemon_agent.schemas.harness.domain import LineCounts, RunResult


def _event(
    kind: str, n: int, content: object, *, episode_id: str = "r-ep1", task_id: str = "t1"
) -> ParsedEvent:
    """一条账（`test_evals_checks._event` 的本地版：episode/task 号可调）。"""
    meta = EventMeta(
        run_id="r", branch="b1", source="t",
        episode_id=episode_id, task_id=task_id, step=n,
    )  # fmt: skip
    return ParsedEvent(
        uuid=f"u{n}",
        kind=kind,  # type: ignore[arg-type]
        type="view",
        started_at=float(n),
        ended_at=float(n) + 0.5,
        meta=meta,
        content=content,
    )  # type: ignore[arg-type]


def test_runresult_roundtrip() -> None:
    result = RunResult(run_id="r1", sample_id="s1", total=1, succeeded=1, success_rate=1.0)

    restored = RunResult.model_validate_json(result.model_dump_json())

    assert restored == result


def test_aggregate_usage_wallclock_and_bounds() -> None:
    events = [
        _event("run_start", 0, {"termination": ""}, episode_id="r", task_id="r"),
        _event(
            "episode_start",
            1,
            EpisodeStartContent(goal_id="g", goal="g", success_criteria="c", max_steps=5),
        ),  # fmt: skip
        _event("act_call", 2, {"key": "a"}),
        _event(
            "choose_call", 3, ModelCallContent(input_tokens=10, output_tokens=3, cached_tokens=1)
        ),
        _event("choose_call", 4, ModelCallContent(input_tokens=5, output_tokens=2)),
        _event("call_failed", 5, CallFailedContent(link="choose", exception="E", reason="r")),
        _event("call_exhausted", 6, CallExhaustedContent(link="judge")),
        _event(
            "episode_end",
            7,
            EpisodeEndContent(
                termination="success", judge_reason="j", tasks_used=1, acts_used=2, reason=""
            ),
        ),
    ]

    usage, counts, started_at, ended_at, bounds = aggregate(events, run_id="r")

    assert usage.calls_by_link == {"choose": 2}
    assert usage.tokens_by_link["choose"].input == 15
    assert usage.tokens_by_link["choose"].output == 5
    assert usage.tokens_by_link["choose"].cached == 1
    assert usage.call_failed == 1
    assert usage.call_exhausted == 1
    assert counts == LineCounts(presses=1, episodes=1, tasks=0)
    assert (started_at, ended_at) == (0.0, 7.5)
    assert [b.episode_id for b in bounds] == ["r-ep1"], "run 级账（episode_id==run_id）不进 bounds"
    assert bounds[0].first_event == "u1" and bounds[0].last_event == "u7"


def test_aggregate_empty_events_is_all_zero() -> None:
    usage, counts, started_at, ended_at, bounds = aggregate([], run_id="r")

    assert usage.calls_by_link == {}
    assert counts == LineCounts()
    assert (started_at, ended_at) == (0.0, 0.0)
    assert bounds == []


def test_fake_run_returns_runresult_with_usage(tmp_path: Path) -> None:
    fake = build_fake(tmp_path)

    result = fake.harness.run("r1", [GOAL], sample_id="s1")

    assert isinstance(result, RunResult)
    assert result.sample_id == "s1"
    assert result.run_id == "r1"
    assert result.branch == "main"
    assert result.outcomes, "假 run 至少跑出一局"
    assert result.total == len(result.outcomes)
    assert result.usage.calls_by_link, "假大脑的调用账要聚合进 usage"
    assert result.usage.call_failed == 0
    assert result.counts.presses > 0 and result.counts.episodes >= 1
    assert result.episode_bounds, "逐局证据边界要非空"
    assert result.started_at > 0 and result.ended_at >= result.started_at


def test_fake_run_checkpoint_only_returns_empty_result(tmp_path: Path) -> None:
    fake = build_fake(tmp_path, checkpoints=True)

    result = fake.harness.run("r1", [GOAL], checkpoint_only=True, sample_id="s1")

    assert result.outcomes == []
    assert result.total == 0
    assert result.usage.calls_by_link == {}
    assert result.counts == LineCounts()
    assert result.sample_id == "s1"
    assert result.termination == ""


@pytest.mark.parametrize("field", ["outcomes", "usage", "episode_bounds"])
def test_runresult_fields_default_to_empty(field: str) -> None:
    result = RunResult(run_id="r1")

    assert getattr(result, field) == [] or getattr(result, field).calls_by_link == {}
