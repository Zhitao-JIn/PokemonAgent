"""指标层（R0 后口径，329）：pass@k/pass^k 归真库 Epochs reducer，本模块只剩过渡期 accuracy/stderr。

真库机制（inspect-ai 0.3.271 实测）：pass@k 与 pass^k **不是独立 Metric**——由
`eval_set(epochs=Epochs(n, reducer=…))` 在打分层出数：

- `pass_at(k)`：随机 k 个 epoch **至少一次成**（即 pass@k，Codex 无偏估计量）；
- `pass_k(k)`：随机 k 个 epoch **全成**（即 pass^k）。

`accuracy()` / `stderr()` 亦为真库 Metric（`MetricProtocol(list[SampleScore])`，挂在
scorer 上）；本模块的同名包装只做一件事——把本项目 Score 的 unjudgeable 摘出分母。
R5 report 改读 `EvalLog.results` 的真库指标后，本文件整体退役。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

from .score import Score

Metric = Callable[[Sequence[Score]], "float | None"]
"""一个指标：一组 Score 聚成一个数；没有可入算的样本时 None（报告里写 n/a）。"""


def _judged(scores: Sequence[Score]) -> list[tuple[str, float]]:
    """可判定的 verdict 型 (sample_id, 1.0/0.0)，其余（graded / unjudgeable）不进指标。"""
    return [
        (s.sample_id, s.value)
        for s in scores
        if s.kind == "verdict" and s.outcome in ("pass", "fail")
    ]


def accuracy(scores: Sequence[Score]) -> float | None:
    """成功率：可判定样本里 pass 的比例。"""
    judged = _judged(scores)
    if not judged:
        return None
    return sum(v for _, v in judged) / len(judged)


def stderr(scores: Sequence[Score]) -> float | None:
    """成功率的标准误 √(p(1−p)/n)；可判定样本 <2 时 None（单样本谈误差无意义）。"""
    judged = _judged(scores)
    if len(judged) < 2:
        return None
    p = sum(v for _, v in judged) / len(judged)
    return math.sqrt(p * (1 - p) / len(judged))


__all__ = ["Metric", "accuracy", "stderr"]
