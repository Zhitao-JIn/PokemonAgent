"""Count observed primitive tile movements; opaque scripts cannot yield exact path length."""

from inspect_ai.scorer import Scorer, scorer

from evals.agent_short_goal_run.dataset.schemas import EvalSample
from pokemon_agent.direct.trace.content import ActCallContent

from .action_observations import action_observations
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


def measure_movement(stream: RunStream, sample: EvalSample) -> Measurement:
    """Count exact endpoint-observed single presses; missing internal paths return None."""
    del sample
    steps = 0
    evidence: list[str] = []
    for pair in action_observations(stream):
        call = pair.event.content
        assert isinstance(call, ActCallContent)
        if call.script or sum(segment.times for segment in call.sequence) != 1:
            return Measurement(
                unit="tiles",
                explanation="Opaque script or multi-press internal path",
                evidence=[pair.event.uuid],
            )
        if (
            pair.before is None
            or pair.after is None
            or (pair.before.place is None or pair.after.place is None)
        ):
            return Measurement(
                unit="tiles",
                explanation="Missing action position boundary",
                evidence=[pair.event.uuid],
            )
        first, last = pair.before.place, pair.after.place
        distance = abs(first.x - last.x) + abs(first.y - last.y)
        changed_map = first.map_id != last.map_id
        if not changed_map and distance > 1:
            return Measurement(
                unit="tiles",
                explanation="Unobserved intermediate movement",
                evidence=[pair.event.uuid],
            )
        steps += 1 if changed_map else distance
        evidence.append(pair.event.uuid)
    return Measurement(
        value=steps,
        unit="tiles",
        explanation="Observed tile moves plus warp transitions",
        evidence=evidence,
    )


@scorer(
    metrics=[measured_count(), successful_median(), successful_p90(), failed_median(), failed_p90()]
)
def movement_steps_scorer(backend: str, stall_limits: tuple[int, int]) -> Scorer:
    """Report physical movement separately from decision count; never estimate script paths."""
    return trace_scorer(measure_movement, backend, stall_limits)
