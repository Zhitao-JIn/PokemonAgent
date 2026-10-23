"""Detect repeated known no-effect actions while preserving dialogue and stochastic progress."""

from inspect_ai.scorer import Scorer, scorer

from evals.agent_short_goal_run.dataset.schemas import EvalSample
from pokemon_agent.direct.trace.content import ActCallContent, SenseFrameContent

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


def _state(frame: SenseFrameContent) -> str:
    """Compare world facts and RAM, not screenshots, lifecycle flags or agent descriptions."""
    return frame.model_dump_json(exclude={"frame", "status", "done", "perceived"})


def measure_repeats(stream: RunStream, sample: EvalSample) -> Measurement:
    """Count unchanged attempts after a known identical no-effect attempt; no actions => None."""
    del sample
    pairs = action_observations(stream)
    previous: tuple[str, str] | None = None
    evidence: list[str] = []
    for pair in pairs:
        call = pair.event.content
        assert isinstance(call, ActCallContent)
        exempt = call.script in {"wait_until_scene", "bounce_in_tall_grass", "circle_walk"}
        if pair.before is None or pair.after is None:
            return Measurement(unit="percent", explanation="Missing observed action boundary")
        before, after = _state(pair.before), _state(pair.after)
        signature = call.model_dump_json(include={"sequence", "script", "args"})
        known_failure = call.script is None or call.code in {"blocked", "no_effect", "still"}
        no_effect = not exempt and known_failure and before == after
        if no_effect and previous == (signature, before):
            evidence.append(pair.event.uuid)
        previous = (signature, after) if no_effect else None
    if not pairs:
        return Measurement(unit="percent", explanation="No executed actions; denominator is zero")
    return Measurement(
        value=100 * len(evidence) / len(pairs),
        unit="percent",
        evidence=evidence,
        explanation="Repeated identical no-effect executions / all executions",
        details={"repeated_actions": len(evidence), "decision_actions": len(pairs)},
    )


@scorer(
    metrics=[measured_count(), successful_median(), successful_p90(), failed_median(), failed_p90()]
)
def ineffective_repetition_scorer(backend: str, stall_limits: tuple[int, int]) -> Scorer:
    """Report useless repetition independently of success, path length and model calls."""
    return trace_scorer(measure_repeats, backend, stall_limits)
