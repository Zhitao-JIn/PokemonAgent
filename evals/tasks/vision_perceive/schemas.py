"""视觉测评的产物与字段判定；机械 RAM 字段归 decode。"""

from __future__ import annotations

from typing import Literal

from inspect_ai.util import StoreModel
from pydantic import BaseModel, Field, model_validator

from pokemon_agent.world import Facts

VISION_FIELDS: tuple[str, ...] = ("scene", "overlay", "dialog_text", "options", "cursor")
SCORE_KEYS: tuple[str, ...] = (*VISION_FIELDS, "parsed")
"""Score 的列：视觉五项各一列，外加"这次尝试解析出来没有"。"""


class PerceiveRun(BaseModel):
    """一次感知尝试的产物。

    契约：`facts` 与 `failure` 恰好一个有值——尝试失败（`PerceptionAttemptFailed`）时没有观测。
    """

    facts: Facts | None = None
    failure: str = ""
    raw: str = Field(default="", description="视觉模型原文（失败时排查用）")
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _facts_xor_failure(self) -> PerceiveRun:
        """观测与失败二选一。"""
        assert (self.facts is None) != (not self.failure), "facts 与 failure 必须恰好一个有值"
        return self


class PerceiveRunRecord(StoreModel):
    """solver 写、scorer 读的唯一交接面。"""

    run: PerceiveRun | None = None


class FieldVerdict(BaseModel):
    """一列的判定：C / I / N（N = 这一帧这一项无从判，不进分母）。"""

    value: Literal["C", "I", "N"]
    got: str = ""
    want: str = ""


__all__ = [
    "SCORE_KEYS",
    "VISION_FIELDS",
    "FieldVerdict",
    "PerceiveRun",
    "PerceiveRunRecord",
]
