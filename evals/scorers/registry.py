"""机械判据注册表：`check_id` → 判据函数。判据是纯函数 `(RunStream, EvalSample) -> CheckVerdict`。

`judge(stream, sample)` 是注册表的唯一入口。**协议收敛后（`scoring/`，spec2 §六）它降为
`mechanical_scorer` / `red_line_scorer` 的内部实现**——判定消费方一律走统一 Scorer，
不许直调本模块（evaluate 的直调已被 328 摘掉）；`CheckVerdict` 是判据的内部返回形状，
出了本包只以 `Score` 的报告投影形态出现。

`check_id` 为 None 时直接 unjudgeable（不可机械判定，不拿模型去猜）。
"""

from __future__ import annotations

from collections.abc import Callable

from evals.dataset.agent_goal_run.schemas import EvalSample
from evals.scorers.verdict import CheckVerdict

from .stream import RunStream

Check = Callable[[RunStream, EvalSample], CheckVerdict]
"""一条机械判据。"""

RULES: dict[str, Check] = {}
"""全部判据，由 `rules/` 下各文件用 `@rule` 登记。"""


def rule(check_id: str) -> Callable[[Check], Check]:
    """登记一条判据；重名当场报错。"""

    def register(fn: Check) -> Check:
        assert check_id not in RULES, f"判据 {check_id} 重复登记"
        RULES[check_id] = fn
        return fn

    return register


def judge(stream: RunStream, sample: EvalSample) -> CheckVerdict:
    """对一条样本跑它的机械判据。

    失败：`check_id` 不在注册表里 → `KeyError`（数据集写错了，当场暴露）。
    """
    if sample.check_id is None:
        return CheckVerdict(outcome="unjudgeable", reason="样本不可机械判定（check_id 为空）")
    if not stream.episodes_for(sample.sample_id):
        return CheckVerdict(outcome="unjudgeable", reason="账本里没有派给这个目标的局")
    return RULES[sample.check_id](stream, sample)


__all__ = ["RULES", "Check", "judge", "rule"]
