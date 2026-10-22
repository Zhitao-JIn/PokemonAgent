"""语义质量分均值与有效样本数；未知评分不当零分处理。"""

import math

from inspect_ai.scorer import CORRECT, INCORRECT, Metric, SampleScore, metric


def values(scores: list[SampleScore]) -> list[float]:
    """兼容旧版 C/I 与新版0..1质量分；仅返回有限、范围内的已评分值。"""
    result: list[float] = []
    for sample in scores:
        value = sample.score.value
        if value in (CORRECT, INCORRECT):
            result.append(float(value == CORRECT))
        elif (
            isinstance(value, (float, int))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and 0 <= value <= 1
        ):
            result.append(float(value))
    return result


@metric(scores="unreduced")
def quality_mean() -> Metric:
    """平均质量分；没有有效评分时为 NaN。"""

    def compute(scores: list[SampleScore]) -> float:
        graded = values(scores)
        return sum(graded) / len(graded) if graded else float("nan")

    return compute


@metric(scores="unreduced")
def quality_count() -> Metric:
    """有效语义评分的样本数，与平均分一起显示。"""

    def compute(scores: list[SampleScore]) -> float:
        return float(len(values(scores)))

    return compute
