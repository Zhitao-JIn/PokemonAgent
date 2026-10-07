"""四格计数指标；只累计原始 0/1，不把四格数量报成比例。"""

from inspect_ai.scorer import Metric, SampleScore, metric


@metric(scores="unreduced")
def confusion_count() -> Metric:
    """每个字段的 0/1 累加得到 TP、FP、FN 或 TN 数量。"""

    def compute(scores: list[SampleScore]) -> float:
        return sum(float(s.score.value) for s in scores if isinstance(s.score.value, (int, float)))

    return compute
