"""汇总 judge 的四格、派生率与分组覆盖。"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from math import nan
from typing import Any

from inspect_ai.scorer import Metric, SampleScore, metric

CONFUSION_CELLS = ("TP", "FP", "FN", "TN")


@dataclass(frozen=True)
class JudgeObservation:
    """一条有效模型响应及其独立真值和分组坐标。"""

    predicted: bool
    achieved: bool
    goal_family: str
    negative_mode: str | None
    task_id: str | None
    episode_id: str | None


def _cells(observations: list[JudgeObservation]) -> Counter[str]:
    counts: Counter[str] = Counter({name: 0 for name in CONFUSION_CELLS})
    for item in observations:
        cell = (
            ("TP" if item.achieved else "FP")
            if item.predicted
            else ("FN" if item.achieved else "TN")
        )
        counts[cell] += 1
    return counts


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else nan


def _summary(
    prefix: str, observations: list[JudgeObservation], include_all_cells: bool
) -> dict[str, int | float]:
    counts = _cells(observations)
    values: dict[str, int | float | None] = {
        f"{prefix}n": len(observations),
        f"{prefix}unique_tasks": len({x.task_id for x in observations if x.task_id}),
        f"{prefix}unique_episodes": len({x.episode_id for x in observations if x.episode_id}),
    }
    if include_all_cells:
        values.update({f"{prefix}{name}": counts[name] for name in CONFUSION_CELLS})
        values[f"{prefix}fpr_denominator"] = counts["FP"] + counts["TN"]
        values[f"{prefix}recall_denominator"] = counts["TP"] + counts["FN"]
        values[f"{prefix}precision_denominator"] = counts["TP"] + counts["FP"]
        values[f"{prefix}accuracy_denominator"] = len(observations)
        values[f"{prefix}fpr"] = _rate(counts["FP"], counts["FP"] + counts["TN"])
        values[f"{prefix}recall"] = _rate(counts["TP"], counts["TP"] + counts["FN"])
        values[f"{prefix}precision"] = _rate(counts["TP"], counts["TP"] + counts["FP"])
        values[f"{prefix}accuracy"] = _rate(counts["TP"] + counts["TN"], len(observations))
    else:
        values[f"{prefix}FP"] = counts["FP"]
        values[f"{prefix}TN"] = counts["TN"]
        values[f"{prefix}fpr_denominator"] = counts["FP"] + counts["TN"]
        values[f"{prefix}fpr"] = _rate(counts["FP"], counts["FP"] + counts["TN"])
    return values


def summarize(observations: list[JudgeObservation]) -> dict[str, int | float]:
    """生成总体、goal_family 与 negative_mode 指标，零分母率使用 NaN。"""
    values = _summary("overall_", observations, include_all_cells=True)
    by_family: dict[str, list[JudgeObservation]] = defaultdict(list)
    by_negative_mode: dict[str, list[JudgeObservation]] = defaultdict(list)
    for item in observations:
        by_family[item.goal_family].append(item)
        if not item.achieved:
            by_negative_mode[item.negative_mode or "other"].append(item)
    for family, members in sorted(by_family.items()):
        values.update(_summary(f"goal_family.{family}.", members, include_all_cells=True))
    for mode, members in sorted(by_negative_mode.items()):
        values.update(_summary(f"negative_mode.{mode}.", members, include_all_cells=False))
    return values


@metric(scores="unreduced")
def judge_summary() -> Metric:
    """从有效评分汇总总体率及 goal_family / negative_mode 分组。"""

    def compute(scores: list[SampleScore]) -> dict[str, int | float]:
        observations: list[JudgeObservation] = []
        for sample_score in scores:
            score = sample_score.score
            metadata: dict[str, Any] = score.metadata or {}
            value = score.value
            assert isinstance(value, dict), "judge scorer must return confusion-cell mapping"
            achieved = bool(value["TP"] or value["FN"])
            predicted = bool(value["TP"] or value["FP"])
            observations.append(
                JudgeObservation(
                    predicted=predicted,
                    achieved=achieved,
                    goal_family=str(metadata.get("goal_family") or "other"),
                    negative_mode=metadata.get("negative_mode"),
                    task_id=metadata.get("task_id"),
                    episode_id=metadata.get("episode_id"),
                )
            )
        return summarize(observations)

    return compute
