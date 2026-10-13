"""统一 Scorer 协议（spec2 §六）：一切判定收敛到 `(RunStream, EvalSample) -> Score`。

inspect-ai 的 `(state, target) -> Score` 在本项目的形状：state = `RunStream`（这条样本
run 的类型化账本；R1 落 RunResult 后主输入换返回值，协议形状不变、只换第一参的类型），
target = `EvalSample`。三套旧协议的收敛位：@rule 机械判据与红线在此包成 Scorer；
现行 e2e 的模型结果评分由独立 Inspect scorer 承载。
"""

from __future__ import annotations

from typing import Protocol

from evals.agent_short_goal_run.dataset.schemas import EvalSample
from evals.agent_short_goal_run.scorer.redlines import red_lines
from evals.agent_short_goal_run.scorer.registry import Check, judge
from evals.agent_short_goal_run.scorer.stream import RunStream

from .score import Score, from_check_verdict, from_red_line_hits


class Scorer(Protocol):
    """一个 scorer：对一条样本判一次，结论是 `Score`。

    前置条件：`stream` 是这条样本对应 run 的账本（可空——scorer 自己给 unjudgeable，不抛）。
    后置条件：返回的 `Score` 带齐 `sample_id`；verdict 型必带 `outcome`。
    """

    def __call__(self, stream: RunStream, sample: EvalSample) -> Score: ...


def mechanical_scorer() -> Scorer:
    """机械判据收敛成的 scorer：转发注册表唯一入口 `judge`。

    `check_id` 为空的样本 unjudgeable（不可机械判定，不拿模型猜——registry 现行为原样）。
    """

    def score(stream: RunStream, sample: EvalSample) -> Score:
        verdict = judge(stream, sample)
        return from_check_verdict(f"mech:{sample.check_id}", verdict, sample_id=sample.sample_id)

    return score


def scorer_from_check(fn: Check, check_id: str) -> Scorer:
    """单条判据包成 scorer（拆条评测 / 单测用；常规路径走 `mechanical_scorer`）。"""

    def score(stream: RunStream, sample: EvalSample) -> Score:
        verdict = fn(stream, sample)
        return from_check_verdict(f"mech:{check_id}", verdict, sample_id=sample.sample_id)

    return score


def red_line_scorer(episode_stall_limit: int, run_stall_limit: int) -> Scorer:
    """红线收敛成的**独立** scorer（spec2 §六：红线独立，命中即判负，不与机械判定混权）。

    R3（谎报成功）需要机械结论做对照——这里内部现算一份：判据是纯函数，重算无副作用；
    将来主输入换 RunResult 时，这份对照改读 RunResult 的 outcomes。

    前置条件：两个 stall 上限来自装配期配置快照（由 task 传入），
    不读被测 live config（spec2 §二边界修正，330）。
    """

    def score(stream: RunStream, sample: EvalSample) -> Score:
        verdict = judge(stream, sample)
        return from_red_line_hits(
            red_lines(
                stream,
                verdict,
                episode_stall_limit=episode_stall_limit,
                run_stall_limit=run_stall_limit,
            ),
            sample_id=sample.sample_id,
        )

    return score


__all__ = ["Scorer", "mechanical_scorer", "red_line_scorer", "scorer_from_check"]
