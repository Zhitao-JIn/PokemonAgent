"""结果动画未结束时已能判定的成功/失败，以及道具消耗不能替代结果。"""

import pytest

from evals.agent_short_goal_run.scorer import judge
from tests.evals.agent_short_goal_run.test_evals_checks import frame, sample, stream


@pytest.mark.parametrize(
    "text",
    [
        "All right! PIDGEY was caught!",
        "PIDGEY was caught!",
        "Darn! The POKéMON broke free!",
        "Oh no! The POKéMON broke free!",
        "Aww! It appeared to be caught!",
        "Aargh! Almost had it!",
        "Shoot! It was so close too!",
    ],
)
def test_ball_result_is_evidence_even_before_inventory_decrement(text):
    events = stream(
        frame(1, in_battle=True, bag={4: 3}),
        frame(2, in_battle=True, bag={4: 3}, dialog=text),
    )

    result = judge(events, sample("ball_thrown"))

    assert result.outcome == "pass"
    assert result.evidence == ["u2"]


def test_ball_consumption_without_a_result_is_not_sufficient():
    events = stream(frame(1, bag={4: 3}), frame(2, bag={4: 2}))

    assert judge(events, sample("ball_thrown")).outcome == "fail"


def test_paginated_capture_result_is_recognized_from_the_complete_second_page() -> None:
    events = stream(
        frame(1, in_battle=True),
        frame(2, in_battle=True, dialog="All right! PIDGEY was"),
        frame(3, in_battle=True, dialog="PIDGEY was caught!"),
    )

    result = judge(events, sample("ball_thrown"))

    assert result.outcome == "pass"
    assert result.evidence == ["u3"]


@pytest.mark.parametrize("text", ["All right! PIDGEY was", "RED used POKé BALL!", "caught"])
def test_incomplete_capture_text_does_not_prove_a_ball_result(text: str) -> None:
    events = stream(frame(1, in_battle=True), frame(2, in_battle=True, dialog=text))

    result = judge(events, sample("ball_thrown"))

    assert result.outcome == "fail"


def test_complete_capture_text_at_start_is_not_new_progress() -> None:
    events = stream(frame(1, dialog="PIDGEY was caught!"), frame(2))

    result = judge(events, sample("ball_thrown"))

    assert result.outcome == "unjudgeable"


@pytest.mark.parametrize("text", ["Got away safel", "Can't escape!", "Can’t escape!"])
def test_escape_result_counts_while_battle_flag_is_still_set(text):
    events = stream(frame(1, in_battle=True), frame(2, in_battle=True, dialog=text))

    assert judge(events, sample("run_attempted")).outcome == "pass"


@pytest.mark.parametrize("text", ["Trying to escape", "Got away", "RUN", "escape"])
def test_incomplete_or_generic_escape_mentions_are_not_results(text):
    events = stream(frame(1, in_battle=True), frame(2, in_battle=True, dialog=text))

    assert judge(events, sample("run_attempted")).outcome == "fail"


def test_a_ball_result_already_present_at_start_is_not_new_progress():
    events = stream(frame(1, dialog="Aww! It appeared to be caught!"), frame(2))

    assert judge(events, sample("ball_thrown")).outcome == "unjudgeable"
