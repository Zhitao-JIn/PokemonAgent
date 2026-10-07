"""现行机械判据和红线的类型化结论。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Outcome = Literal["pass", "fail", "unjudgeable"]


class CheckVerdict(BaseModel):
    """机械判据的结论。"""

    outcome: Outcome
    evidence: list[str] = Field(default_factory=list, description="支撑结论的事件 uuid")
    reason: str


class RedLineHit(BaseModel):
    """命中的一条红线。"""

    line_id: str
    evidence: list[str] = Field(default_factory=list)
    reason: str


__all__ = ["CheckVerdict", "RedLineHit", "Outcome"]
