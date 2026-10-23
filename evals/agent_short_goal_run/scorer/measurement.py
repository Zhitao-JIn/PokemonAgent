"""Trace-only measurement contract; missing evidence is distinct from a measured zero."""

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from evals.agent_short_goal_run.dataset.schemas import EvalSample

from .stream import RunStream


class Measurement(BaseModel):
    """One metric's value, unit and audit evidence; None means unavailable, never failure."""

    model_config = ConfigDict(frozen=True)

    value: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    unit: str
    explanation: str
    evidence: list[str] = Field(default_factory=list)
    details: dict[str, JsonValue] = Field(default_factory=dict)


class TraceMeasurement(Protocol):
    """Consume an ordered run and its frozen sample without tools or model calls."""

    def __call__(self, stream: RunStream, sample: EvalSample) -> Measurement:
        """Return a measurement or an explicit missing reason.

        Caller supplies one ordered execution branch and the matching sample. Missing or
        incomplete evidence returns value=None; malformed typed data propagates its error.
        """
        ...
