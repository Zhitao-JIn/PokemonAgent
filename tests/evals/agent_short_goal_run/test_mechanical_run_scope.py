"""run 级机械判定跟随整个执行线，重规划不会截断证据。"""

from __future__ import annotations

import pytest
from test_evals_checks import _event, frame, sample, stream

from evals.agent_short_goal_run.scorer import RunStream, mechanical_scorer
from pokemon_agent.direct.trace import ParsedEvent
from pokemon_agent.direct.trace.content import EpisodeStartContent, OtherContent


def in_episode(episode_id: str, event: ParsedEvent) -> ParsedEvent:
    """保留同一 run 与分支，把事件挪到指定局。"""
    return event.model_copy(
        update={"meta": event.meta.model_copy(update={"episode_id": episode_id})}
    )


def in_replanned_episode(event: ParsedEvent) -> ParsedEvent:
    """保留同一 run 与分支，将事件放到新增目标的第二局。"""
    return in_episode("r-ep2", event)


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


def started_episode(episode_id: str, goal_id: str, n: int) -> ParsedEvent:
    """在指定局上放一条开局账；目标 id 由 planner 新建。"""
    content = EpisodeStartContent(
        goal_id=goal_id, goal="换一条路线", success_criteria="进入建筑", max_steps=4
    )
    return in_episode(episode_id, _event("episode_start", n, content))


def split_goal_stream(*second_episode: ParsedEvent) -> RunStream:
    """原样本 id 名下一局都没有：两局分别挂在 planner 新建的两个目标上。"""
    return RunStream(
        [
            started_episode("r-ep1", "plan-r-1", 0),
            in_episode("r-ep1", frame(1, map_id=1)),
            in_episode("r-ep1", frame(2, map_id=1)),
            started_episode("r-ep2", "plan-r-2", 3),
            *second_episode,
        ]
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


def test_run_sample_judges_episodes_under_planner_created_goal_ids() -> None:
    """run 粒度的证据是本执行线，不看开局账上的目标 id。"""
    events = split_goal_stream(in_episode("r-ep2", frame(4, map_id=40)))

    result = mechanical_scorer()(events, sample("map_changed"))

    assert result.outcome == "pass"
    assert result.evidence == ["u1", "u4"]


def test_episode_sample_still_needs_its_own_goal_in_the_ledger() -> None:
    """同一份拆解账对 episode 粒度仍是 unjudgeable：那个目标 id 从没开过局。"""
    events = split_goal_stream(in_episode("r-ep2", frame(4, map_id=40)))
    case = sample("map_changed").model_copy(update={"granularity": "episode"})

    result = mechanical_scorer()(events, case)

    assert result.outcome == "unjudgeable"


def test_two_npc_check_reads_dialog_events_from_a_later_episode() -> None:
    """两位 NPC 的对话分散在两局，且两局的目标 id 都是 planner 新建的。"""
    events = RunStream(
        [
            started_episode("r-ep1", "plan-r-1", 0),
            in_episode("r-ep1", frame(1, people=((2, 5), (4, 3), (6, 4)))),
            started_episode("r-ep2", "plan-r-2", 2),
            in_episode(
                "r-ep2",
                _event(
                    "write_object_memory",
                    3,
                    OtherContent(
                        object_kind="人", outcome="dialog", place={"map_id": 1, "x": 2, "y": 5}
                    ),
                ),
            ),
            in_episode(
                "r-ep2",
                _event(
                    "write_object_memory",
                    4,
                    OtherContent(
                        object_kind="人", outcome="dialog", place={"map_id": 1, "x": 4, "y": 3}
                    ),
                ),
            ),
        ]
    )

    result = mechanical_scorer()(events, sample("shop_two_npcs_interacted"))

    assert result.outcome == "pass"
    assert result.evidence == ["u3", "u4"]


def test_a_run_sample_without_any_episode_is_unjudgeable() -> None:
    """闸门仍在：本执行线上一局都没有，判据无从下手。"""
    result = mechanical_scorer()(RunStream([]), sample("map_changed"))

    assert result.outcome == "unjudgeable"


def test_an_episode_sample_is_not_judged_from_another_goal() -> None:
    """episode / task 粒度仍按目标 id 取局；run 粒度按 run 取（口径见上面的用例）。"""
    events = replanned_stream(frame(4, map_id=40))
    case = sample("map_changed").model_copy(
        update={"sample_id": "another_sample", "granularity": "episode"}
    )

    result = mechanical_scorer()(events, case)

    assert result.outcome == "unjudgeable"
