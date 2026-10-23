"""Measure run wall time without adding overlapping nested spans."""

from inspect_ai.scorer import Scorer, scorer

from evals.agent_short_goal_run.dataset.schemas import EvalSample

from .measurement import Measurement
from .numeric_metrics import (
    failed_median,
    failed_p90,
    measured_count,
    successful_median,
    successful_p90,
)
from .stream import RunStream
from .trace_adapter import trace_scorer


def measure_duration(stream: RunStream, sample: EvalSample) -> Measurement:
    """Measure run wall time without adding overlapping nested spans."""
    del sample
    starts, ends = stream.of_kind("run_start"), stream.of_kind("run_end")
    if len(starts) != 1 or len(ends) != 1:
        return Measurement(unit="seconds", explanation="Missing or ambiguous run boundaries")
    duration = ends[0].ended_at - starts[0].started_at
    if duration < 0:
        return Measurement(unit="seconds", explanation="Run end precedes start")
    return Measurement(
        value=duration,
        unit="seconds",
        explanation="Wall time between run boundaries",
        evidence=[starts[0].uuid, ends[0].uuid],
    )


@scorer(
    metrics=[measured_count(), successful_median(), successful_p90(), failed_median(), failed_p90()]
)
def run_duration_scorer(backend: str, stall_limits: tuple[int, int]) -> Scorer:
    """Expose one trace metric with outcome-conditioned summaries."""
    return trace_scorer(measure_duration, backend, stall_limits)
