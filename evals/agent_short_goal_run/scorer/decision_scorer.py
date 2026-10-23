"""Count actual executions; model retries are not game actions."""

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


def measure_decisions(stream: RunStream, sample: EvalSample) -> Measurement:
    """Count actual executions; model retries are not game actions."""
    del sample
    events = stream.of_kind("act_call")
    return Measurement(
        value=len(events),
        unit="actions",
        explanation="Executed decisions; each script counts once",
        evidence=[event.uuid for event in events],
    )


@scorer(
    metrics=[measured_count(), successful_median(), successful_p90(), failed_median(), failed_p90()]
)
def decision_actions_scorer(backend: str, stall_limits: tuple[int, int]) -> Scorer:
    """Expose one trace metric with outcome-conditioned summaries."""
    return trace_scorer(measure_decisions, backend, stall_limits)
