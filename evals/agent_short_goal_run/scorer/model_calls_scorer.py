"""Count model attempts across all agent links, including retries and summaries."""

from inspect_ai.scorer import Scorer, scorer

from evals.agent_short_goal_run.dataset.schemas import EvalSample
from pokemon_agent.direct.trace.content import ModelCallContent

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


def measure_model_calls(stream: RunStream, sample: EvalSample) -> Measurement:
    """Count model attempts across all agent links, including retries and summaries."""
    del sample
    events = [event for event in stream.events if isinstance(event.content, ModelCallContent)]
    return Measurement(
        value=len(events),
        unit="calls",
        explanation="All traced model attempts including failures",
        evidence=[event.uuid for event in events],
    )


@scorer(
    metrics=[measured_count(), successful_median(), successful_p90(), failed_median(), failed_p90()]
)
def model_calls_scorer(backend: str, stall_limits: tuple[int, int]) -> Scorer:
    """Expose one trace metric with outcome-conditioned summaries."""
    return trace_scorer(measure_model_calls, backend, stall_limits)
