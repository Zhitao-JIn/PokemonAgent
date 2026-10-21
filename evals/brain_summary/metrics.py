"""分层质量宏平均、有效数和重大失真率；缺一层不缩小宏平均分母。"""

from collections.abc import Sequence
from math import nan

from inspect_ai.scorer import CORRECT, Metric, SampleScore, metric

from .contract import DIMENSIONS, LAYERS, SummaryReview
from .grading import quality_value, review_pass


def average(values: Sequence[float]) -> float:
    """仅对调用方给出的已知值求均值；空集合未知。"""
    return sum(values) / len(values) if values else nan


def review_metrics(reviews: list[SummaryReview]) -> dict[str, int | float]:
    """完整质量分母、各维分母、重大失真与审阅通过分母相互独立。"""
    complete = [value for review in reviews if isinstance(value := quality_value(review), float)]
    distortions = [
        float(review.major_distortion.present)
        for review in reviews
        if review.major_distortion.present is not None
    ]
    passes = [value for review in reviews if (value := review_pass(review)) is not None]
    result: dict[str, int | float] = {
        "quality_n": len(complete),
        "quality_mean": average(complete),
        "major_distortion_n": len(distortions),
        "major_distortion_rate": average(distortions),
        "review_pass_n": len(passes),
        "review_pass_rate": average(passes),
    }
    for name in DIMENSIONS:
        values = [
            item.score
            for review in reviews
            for item in review.dimensions
            if item.name == name and item.score is not None
        ]
        result[f"{name}_n"], result[f"{name}_mean"] = len(values), average(values)
    return result


@metric(scores="unreduced")
def summary_quality() -> Metric:
    """总体质量为三层宏平均；同时报告逐样本均值与各层有效数量。"""

    def compute(scores: list[SampleScore]) -> dict[str, int | float]:
        groups: dict[str, list[SummaryReview]] = {layer: [] for layer in LAYERS}
        for sample in scores:
            metadata = sample.score.metadata or {}
            if metadata.get("review") is not None and metadata.get("layer") in groups:
                groups[metadata["layer"]].append(SummaryReview.model_validate(metadata["review"]))
        result = review_metrics([review for group in groups.values() for review in group])
        result["scored_samples_n"] = len(scores)
        result["sample_quality_mean"] = result.pop("quality_mean")
        layer_values = []
        for layer, group in groups.items():
            metrics = review_metrics(group)
            result.update({f"{layer}_{key}": value for key, value in metrics.items()})
            if metrics["quality_n"]:
                layer_values.append(float(metrics["quality_mean"]))
        result["quality_layers_n"] = len(layer_values)
        result["quality_mean"] = average(layer_values) if len(layer_values) == 3 else nan
        return result

    return compute


@metric(scores="unreduced")
def summary_contract() -> Metric:
    """契约通过率是机械结果，与模型审阅通过率分开显示。"""

    def compute(scores: list[SampleScore]) -> dict[str, int | float]:
        result: dict[str, int | float] = {}
        for layer in ("all", *LAYERS):
            group = [
                sample
                for sample in scores
                if layer == "all" or (sample.score.metadata or {}).get("layer") == layer
            ]
            result[f"{layer}_contract_n"] = len(group)
            result[f"{layer}_contract_pass_rate"] = average(
                [float(sample.score.value == CORRECT) for sample in group]
            )
        return result

    return compute
