"""只算"判得了"的样本的指标：NOANSWER 不进分母。

inspect 自带的 `accuracy()` 把 NOANSWER 当 0 分算进分母——"这一帧没有对话框，所以对话文字
无从判对错"会被记成判错。字段级测评（perceive）与机械判定里"不可判定"的样本都用这里的指标。
"""

from __future__ import annotations

from inspect_ai.scorer import CORRECT, INCORRECT, Metric, SampleScore, metric


def _judged(scores: list[SampleScore]) -> list[bool]:
    """判得了的样本：CORRECT → True，INCORRECT → False，其余丢弃。"""
    return [s.score.value == CORRECT for s in scores if s.score.value in (CORRECT, INCORRECT)]


@metric(scores="unreduced")
def judged_accuracy() -> Metric:
    """判得了的样本里判对的比例；一条都判不了时为 NaN（报表里显示 n/a 的语义）。"""

    def compute(scores: list[SampleScore]) -> float:
        judged = _judged(scores)
        return sum(judged) / len(judged) if judged else float("nan")

    return compute


@metric(scores="unreduced")
def judged_count() -> Metric:
    """判得了的样本数（分母多大，准确率才有意义）。"""

    def compute(scores: list[SampleScore]) -> float:
        return float(len(_judged(scores)))

    return compute


__all__ = ["judged_accuracy", "judged_count"]
