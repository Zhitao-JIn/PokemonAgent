"""run 级机械判定跟随整个执行线，重规划不会截断证据。"""

from __future__ import annotations

import pytest
from test_evals_checks import _event, frame, sample, stream

from evals.agent_short_goal_run.scorer import RunStream, mechanical_scorer
from pokemon_agent.direct.trace import ParsedEvent
from pokemon_agent.direct.trace.content import EpisodeStartContent


def in_replanned_episode(event: ParsedEvent) -> ParsedEvent:
    """保留同一 run 与分支，将事件放到新增目标的第二局。"""
    return event.model_copy(update={"meta": event.meta.model_copy(update={"episode_id": "r-ep2"})})


def replanned_stream(*later_frames: ParsedEvent) -> RunStream:
    """原目标第一局未换图，后续局在同一 run 内执行新目标。"""
    first = stream(frame(1, map_id=1), frame(2, map_id=1))
    next_goal = EpisodeStartContent(
        goal_id="plan-r-1", goal="换一条路线", success_criteria="进入建筑", max_steps=4
    )
    start = in_replanned_episode(_event("episode_start", 3, next_goal))
    return RunStream(
        [*first.events, start, *(in_replanned_episode(event) for event in later_frames)]
    )


@pytest.mark.parametrize(("granularity", "outcome"), [("run", "pass"), ("episode", "fail")])
def test_replanned_success_is_included_only_for_run_samples(granularity: str, outcome: str) -> None:
    events = replanned_stream(frame(4, map_id=40))
    case = sample("map_changed").model_copy(update={"granularity": granularity})

    result = mechanical_scorer()(events, case)

    assert result.outcome == outcome
    assert result.evidence == (["u1", "u4"] if granularity == "run" else ["u1", "u2"])


def test_run_state_check_still_requires_success_in_the_final_frame() -> None:
    events = replanned_stream(frame(4, map_id=40), frame(5, map_id=1))

    result = mechanical_scorer()(events, sample("map_changed"))

    assert result.outcome == "fail"
    assert result.evidence == ["u1", "u5"]


def test_run_state_check_does_not_accept_a_menu_closed_after_replanning() -> None:
    events = replanned_stream(
        frame(4, options=("BUY", "SELL", "QUIT")),
        frame(5),
    )

    result = mechanical_scorer()(events, sample("shop_menu_opened"))

    assert result.outcome == "fail"
    assert result.evidence == ["u5"]


def test_an_unrelated_run_is_not_accepted_as_sample_evidence() -> None:
    events = replanned_stream(frame(4, map_id=40))
    case = sample("map_changed").model_copy(update={"sample_id": "another_sample"})

    result = mechanical_scorer()(events, case)

    assert result.outcome == "unjudgeable"
