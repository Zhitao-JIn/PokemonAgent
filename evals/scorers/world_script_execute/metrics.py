"""按用例类别分组的独立指标名，避免 Inspect 同名 grouped 指标互相覆盖。"""

from inspect_ai.scorer import Metric, accuracy, grouped, metric


@metric
def kind_accuracy() -> Metric:
    """按 sample metadata 的 kind 报成功率；调用方须为每条样本填写 kind。"""
    return grouped(accuracy(), "kind", all=False)
