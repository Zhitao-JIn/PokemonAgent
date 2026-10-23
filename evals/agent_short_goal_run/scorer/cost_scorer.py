"""Aggregate explicit agent charges; token counts alone do not establish a monetary cost."""

from inspect_ai.scorer import Scorer, scorer
from pydantic import BaseModel, ConfigDict, Field

from evals.agent_short_goal_run.dataset.schemas import EvalSample
from pokemon_agent.direct.trace.content import ModelCallContent

from .measurement import Measurement
from .numeric_metrics import cost_per_success, measured_count
from .stream import RunStream
from .trace_adapter import trace_scorer


class RecordedCharge(BaseModel):
    """Optional explicit charge contract; no price lookup or inferred currency is permitted."""

    model_config = ConfigDict(extra="ignore")
    cost: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    currency: str | None = Field(default=None, min_length=1)


def measure_cost(stream: RunStream, sample: EvalSample) -> Measurement:
    """Sum all model attempts only when every charge has an explicit matching currency.

    Current trace contains usage, not prices; such runs return None with usage metadata.
    Cached input and reasoning are reported as subsets, never added to total tokens twice.
    """
    del sample
    calls = [e for e in stream.events if isinstance(e.content, ModelCallContent)]
    usage = {
        name: sum(getattr(e.content, name) for e in calls)
        for name in (
            "input_tokens",
            "output_tokens",
            "cached_tokens",
            "reasoning_tokens",
        )
    }
    charges = [RecordedCharge.model_validate(e.content.model_dump()) for e in calls]
    currencies = {charge.currency for charge in charges}
    if not calls or any(c.cost is None or c.currency is None for c in charges):
        return Measurement(
            unit="currency",
            explanation="Trace has no complete monetary charges; tokens preserved",
            details=usage,
        )
    if len(currencies) != 1:
        return Measurement(
            unit="currency", explanation="Mixed currencies cannot be summed", details=usage
        )
    currency = charges[0].currency
    assert currency is not None
    return Measurement(
        value=sum(c.cost for c in charges if c.cost is not None),
        unit=currency,
        explanation="Explicit agent charges including failed attempts",
        details=usage,
        evidence=[e.uuid for e in calls],
    )


@scorer(metrics=[measured_count(), cost_per_success()])
def success_cost_scorer(backend: str, stall_limits: tuple[int, int]) -> Scorer:
    """Store per-attempt charges and aggregate all attempt costs over factual successes."""
    return trace_scorer(measure_cost, backend, stall_limits)
