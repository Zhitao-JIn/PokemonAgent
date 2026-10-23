"""Unreduced trace summaries keep unknown evidence out and successes separate from failures."""

import math
from statistics import median
from typing import Literal

from inspect_ai.scorer import Metric, SampleScore, metric


def _values(scores: list[SampleScore], successful: bool | None = None) -> list[float]:
    """Select finite numeric values, optionally conditioned on factual run success."""
    return [
        float(item.score.value)
        for item in scores
        if isinstance(item.score.value, (int, float))
        and math.isfinite(item.score.value)
        and (successful is None or (item.score.metadata or {}).get("successful") is successful)
    ]


@metric(scores="unreduced")
def measured_count() -> Metric:
    """Report the observed denominator, including actual zero values."""

    def compute(scores: list[SampleScore]) -> float:
        return float(len(_values(scores)))

    return compute


def group_summary(successful: bool, statistic: Literal["median", "p90"]) -> Metric:
    """Summarize one outcome group; P90 uses linear interpolation of ordered samples."""

    def compute(scores: list[SampleScore]) -> float:
        values = sorted(_values(scores, successful))
        if not values:
            return float("nan")
        if statistic == "median":
            return float(median(values))
        index = (len(values) - 1) * 0.9
        lower = math.floor(index)
        upper = math.ceil(index)
        return values[lower] + (values[upper] - values[lower]) * (index - lower)

    return compute


@metric(scores="unreduced")
def successful_median() -> Metric:
    """Median among successful, observed runs."""
    return group_summary(True, "median")


@metric(scores="unreduced")
def successful_p90() -> Metric:
    """P90 among successful, observed runs."""
    return group_summary(True, "p90")


@metric(scores="unreduced")
def failed_median() -> Metric:
    """Median among failed, observed runs."""
    return group_summary(False, "median")


@metric(scores="unreduced")
def failed_p90() -> Metric:
    """P90 among failed, observed runs."""
    return group_summary(False, "p90")


@metric(scores="unreduced")
def cost_per_success() -> Metric:
    """Sum all valid attempt costs over successes; any missing cost/outcome makes it unknown."""

    def compute(scores: list[SampleScore]) -> float:
        attempts = [s for s in scores if not (s.score.metadata or {}).get("invalid", False)]
        costs = _values(attempts)
        metadata = [s.score.metadata or {} for s in attempts]
        if len(costs) != len(attempts) or any(m.get("successful") is None for m in metadata):
            return float("nan")
        currencies = {m.get("unit") for m in metadata}
        successes = sum(m.get("successful") is True for m in metadata)
        if not successes or len(currencies) != 1:
            return float("nan")
        return sum(costs) / successes

    return compute
