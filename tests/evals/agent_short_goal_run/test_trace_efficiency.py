"""Independent metric examples distinguish measured zero, failures and missing evidence."""

import pytest
from _efficiency_fixtures import action, event, example_sample, example_stream, frame

from evals.agent_short_goal_run.scorer.cost_scorer import measure_cost
from evals.agent_short_goal_run.scorer.decision_scorer import measure_decisions
from evals.agent_short_goal_run.scorer.duration_scorer import measure_duration
from evals.agent_short_goal_run.scorer.model_calls_scorer import measure_model_calls
from evals.agent_short_goal_run.scorer.movement_scorer import measure_movement
from evals.agent_short_goal_run.scorer.overshoot_scorer import measure_overshoot
from evals.agent_short_goal_run.scorer.repeat_scorer import measure_repeats
from pokemon_agent.direct.trace.content import ModelCallContent, OtherContent


def test_decisions_count_executions_including_scripts_but_not_choose_retries():
    stream = example_stream(
        event("choose_call", ModelCallContent(ok=False)),
        event("choose_call", ModelCallContent()),
        action(),
        action("walk_to", script=True),
    )

    result = measure_decisions(stream, example_sample())

    assert result.value == 2


def test_model_calls_count_all_attempts_without_double_counting_error_events():
    stream = example_stream(
        event("choose_call", ModelCallContent(ok=False)),
        event("call_failed", OtherContent()),
        event("choose_call", ModelCallContent()),
        event("judge_call", ModelCallContent()),
        event("summarize_run_call", ModelCallContent()),
        action(),
    )

    result = measure_model_calls(stream, example_sample())

    assert result.value == 4


def test_movement_counts_tiles_and_warps_but_not_blocked_moves_or_turns():
    stream = example_stream(
        frame(),
        action(),
        frame(2),
        action(),
        frame(2),
        action("up"),
        frame(2, facing="south"),
        action("down"),
        frame(9, map_id=2),
    )

    result = measure_movement(stream, example_sample())

    assert result.value == 2


def test_script_movement_is_missing_instead_of_estimated_from_endpoints():
    stream = example_stream(frame(), action("walk_to", script=True), frame(8))

    result = measure_movement(stream, example_sample())

    assert result.value is None
    assert "script" in result.explanation


def test_multi_press_and_missing_after_frame_do_not_hide_unobserved_movement():
    for events in ((frame(), action(times=3), frame(4)), (frame(), action())):
        result = measure_movement(example_stream(*events), example_sample())

        assert result.value is None


def test_repeated_no_effect_actions_count_only_repeats_after_the_first_failure():
    stream = example_stream(frame(), action(), frame(), action(), frame(), action(), frame())

    result = measure_repeats(stream, example_sample())

    assert result.value == pytest.approx(200 / 3)
    assert result.details["repeated_actions"] == 2


def test_dialogue_progress_and_waiting_are_not_useless_repetition():
    stream = example_stream(
        frame(text="Hello"),
        action("a"),
        frame(text="Welcome"),
        action("a"),
        frame(text="Goodbye"),
        action("wait_until_scene", script=True),
        frame(text="Goodbye"),
        action("wait_until_scene", script=True),
        frame(text="Goodbye"),
    )

    result = measure_repeats(stream, example_sample())

    assert result.value == 0


def test_successful_script_with_no_visible_change_is_not_known_to_have_failed():
    stream = example_stream(
        frame(),
        action("talk_to_adjacent_npc", script=True),
        frame(),
        action("talk_to_adjacent_npc", script=True),
        frame(),
    )

    assert measure_repeats(stream, example_sample()).value == 0


def test_overshoot_uses_first_factual_success_even_if_agent_later_undoes_it():
    stream = example_stream(
        frame(),
        action(),
        frame(map_id=2),
        action("down"),
        frame(),
        action(),
        frame(),
    )

    result = measure_overshoot(stream, example_sample())

    assert result.value == 2
    assert result.details["check_id"] == "map_changed"


def test_overshoot_is_missing_when_never_achieved_or_no_factual_check_exists():
    stream = example_stream(frame(), action(), frame())

    assert measure_overshoot(stream, example_sample()).value is None
    assert measure_overshoot(stream, example_sample(None)).value is None


def test_duration_uses_run_boundaries_not_sums_of_nested_event_durations():
    stream = example_stream(frame(), action(), frame())
    stream.events[-1].ended_at = 20

    assert measure_duration(stream, example_sample()).value == 20
    assert measure_duration(example_stream(complete=False), example_sample()).value is None


def test_cost_without_money_evidence_preserves_tokens_and_reports_missing():
    stream = example_stream(
        event(
            "choose_call",
            ModelCallContent(
                input_tokens=100,
                output_tokens=20,
                cached_tokens=40,
                reasoning_tokens=10,
            ),
        )
    )

    result = measure_cost(stream, example_sample())

    assert result.value is None
    assert result.details["input_tokens"] == 100
    assert result.details["output_tokens"] == 20
    assert result.details["reasoning_tokens"] == 10


def test_explicit_recorded_charges_are_summed_only_with_matching_currency():
    stream = example_stream(
        event("choose_call", ModelCallContent(cost=0.2, currency="CNY")),
        event("judge_call", ModelCallContent(cost=0.3, currency="CNY")),
    )

    result = measure_cost(stream, example_sample())

    assert result.value == 0.5
    assert result.unit == "CNY"
    stream.events[-2].content.currency = "USD"
    assert measure_cost(stream, example_sample()).value is None
