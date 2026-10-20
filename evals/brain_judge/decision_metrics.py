"""完整 judge 决策统计；旧二元标签不被猜补为 continue 或 blocked。"""

from math import nan

from inspect_ai.scorer import Metric, SampleScore, metric

DECISIONS = ("achieved", "continue", "blocked", "interrupted")


def summarize_decisions(pairs: list[tuple[str, str]]) -> dict[str, int | float]:
    """输入为独立标签、候选结论；返回四乘四矩阵和每类分母。"""
    values: dict[str, int | float] = {"decision_n": len(pairs)}
    for expected in DECISIONS:
        group = [(gold, predicted) for gold, predicted in pairs if gold == expected]
        values[f"decision_{expected}_n"] = len(group)
        values[f"decision_{expected}_accuracy"] = (
            sum(gold == predicted for gold, predicted in group) / len(group) if group else nan
        )
        for predicted in DECISIONS:
            values[f"decision_{expected}_to_{predicted}"] = sum(
                gold == expected and candidate == predicted for gold, candidate in pairs
            )
    values["decision_accuracy"] = (
        sum(gold == predicted for gold, predicted in pairs) / len(pairs) if pairs else nan
    )
    return values


@metric
def decision_summary() -> Metric:
    """仅完整且独立标过 decision 的样本进入多类别分母。"""

    def compute(scores: list[SampleScore]) -> dict[str, int | float]:
        pairs = []
        for sample in scores:
            metadata = sample.score.metadata or {}
            gold, predicted = metadata.get("expected_decision"), metadata.get("decision")
            if gold in DECISIONS and predicted in DECISIONS:
                pairs.append((gold, predicted))
        return summarize_decisions(pairs)

    return compute
