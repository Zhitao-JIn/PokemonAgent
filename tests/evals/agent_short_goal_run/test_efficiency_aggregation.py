"""Aggregation examples use unreduced epochs and never hide failed-attempt costs."""

import math

from inspect_ai.scorer import NOANSWER, SampleScore, Score

from evals.agent_short_goal_run.scorer.numeric_metrics import (
    cost_per_success,
    failed_median,
    failed_p90,
    measured_count,
    successful_median,
    successful_p90,
)


def measured(value, successful=True, unit="CNY", invalid=False):
    return SampleScore(
        sample_id="same-goal",
        score=Score(
            value=value,
            metadata={
                "successful": successful,
                "unit": unit,
                "invalid": invalid,
            },
        ),
    )


def test_success_and_failure_summaries_keep_all_epochs_and_exclude_missing():
    scores = [measured(0), measured(10), measured(100, False), measured(NOANSWER)]

    assert measured_count()(scores) == 3
    assert successful_median()(scores) == 5
    assert successful_p90()(scores) == 9
    assert failed_median()(scores) == failed_p90()(scores) == 100


def test_cost_per_success_includes_failed_attempts_in_the_numerator():
    scores = [measured(2), measured(3), measured(7, False)]

    assert cost_per_success()(scores) == 6


def test_missing_failure_cost_is_not_silently_excluded_to_make_success_cheaper():
    scores = [measured(2), measured(NOANSWER, False)]

    assert math.isnan(cost_per_success()(scores))


def test_cost_without_success_or_with_unknown_outcomes_or_mixed_units_is_unavailable():
    for scores in (
        [measured(2, False)],
        [measured(2, None)],
        [measured(2), measured(3, unit="USD")],
    ):
        assert math.isnan(cost_per_success()(scores))


def test_invalid_start_records_are_not_valid_paid_attempts():
    scores = [measured(2), measured(NOANSWER, invalid=True)]

    assert cost_per_success()(scores) == 2


def test_empty_groups_are_unavailable_instead_of_zero():
    assert math.isnan(failed_median()([measured(5)]))
    assert math.isnan(successful_p90()([]))
