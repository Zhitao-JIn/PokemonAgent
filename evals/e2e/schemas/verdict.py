"""一条样本的判定结果（`docs/eval/spec.md` §七、§十）：红线、结果、judge 一致性、rubric、效率。

四块互不加权；`final` 只由红线与结果决定（红线命中即 fail）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Outcome = Literal["pass", "fail", "unjudgeable"]
"""机械判定的三种结论。"""

JudgeCellName = Literal["TP", "FP", "FN", "TN", "n/a"]
"""judge 结论（说成 / 没说成）× 机械结论（pass / fail）；机械 unjudgeable 时为 n/a。"""


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


class JudgeCell(BaseModel):
    """一层 judge 与机械结论的对照。"""

    layer: Literal["run", "episode"]
    judge_done: bool
    mech: Outcome
    cell: JudgeCellName


class RubricScore(BaseModel):
    """rubric 一条的得分；人工条目未打分时 `score` 为 None。"""

    item_id: str
    grader: Literal["code", "human", "model"]
    score: int | None = None
    detail: dict[str, float] = Field(default_factory=dict, description="打分所依据的原始量")


class TokenUse(BaseModel):
    """一条链路的 token 用量。"""

    input: int = 0
    output: int = 0
    cached: int = 0
    reasoning: int = 0


class Efficiency(BaseModel):
    """效率层（spec §十）。"""

    tokens_by_link: dict[str, TokenUse] = Field(default_factory=dict)
    calls_by_link: dict[str, int] = Field(default_factory=dict)
    call_failed: int = 0
    call_exhausted: int = 0
    presses: int = 0
    episodes: int = 0
    tasks: int = 0
    wall_seconds: float = 0.0


class SenseAgreement(BaseModel):
    """感知过程集：看档帧上视觉 `scene=battle` 与内存战斗标志的一致帧数。"""

    frames: int = 0
    agree: int = 0


class SampleResult(BaseModel):
    """一条样本的全部判定。`invalid` 非空时其余块不计入任何分母。"""

    sample_id: str
    category: str
    split: str
    invalid: str = Field(default="", description="样本无效的原因；空串 = 有效")
    run_id: str = ""
    branch: str = ""
    termination: str = ""
    red_lines: list[RedLineHit] = Field(default_factory=list)
    verdict: CheckVerdict | None = None
    final: Outcome = "unjudgeable"
    judge: list[JudgeCell] = Field(default_factory=list)
    task_terminations: dict[str, int] = Field(default_factory=dict)
    rubric: list[RubricScore] = Field(default_factory=list)
    efficiency: Efficiency = Field(default_factory=Efficiency)
    sense: SenseAgreement = Field(default_factory=SenseAgreement)


__all__ = [
    "CheckVerdict",
    "Efficiency",
    "JudgeCell",
    "JudgeCellName",
    "Outcome",
    "RedLineHit",
    "RubricScore",
    "SampleResult",
    "SenseAgreement",
    "TokenUse",
]
