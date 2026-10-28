"""Locate first factual completion from trace prefixes, never from agent judge claims."""

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
from .scorer import mechanical_scorer
from .stream import RunStream
from .trace_adapter import trace_scorer


def measure_overshoot(stream: RunStream, sample: EvalSample) -> Measurement:
    """Replay the existing frozen factual check over prefixes and count subsequent actions.

    The check_id remains the evaluator's truth contract. Never-achieved and uncheckable goals
    are unavailable, not zero. Missing script-internal evidence cannot identify internal time.
    """
    if sample.check_id is None:
        return Measurement(unit="actions", explanation="No factual completion check")
    check = mechanical_scorer()
    for index, event in enumerate(stream.events):
        if event.kind not in {"sense_frame", "act_call", "write_act_memory"}:
            continue
        result = check(RunStream(stream.events[: index + 1]), sample)
        if result.outcome == "pass":
            remaining = sum(e.kind == "act_call" for e in stream.events[index + 1 :])
            return Measurement(
                value=remaining,
                unit="actions",
                evidence=[event.uuid],
                explanation="Decisions after first observed factual completion",
                details={"check_id": sample.check_id, "completion_event": event.uuid},
            )
    return Measurement(unit="actions", explanation="No observed factual completion")


@scorer(
    metrics=[measured_count(), successful_median(), successful_p90(), failed_median(), failed_p90()]
)
def post_completion_actions_scorer(backend: str, stall_limits: tuple[int, int]) -> Scorer:
    """Report extra decisions even when an agent later undoes a completed state."""
    return trace_scorer(measure_overshoot, backend, stall_limits)
