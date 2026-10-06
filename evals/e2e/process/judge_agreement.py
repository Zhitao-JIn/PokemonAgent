"""judge 过程集（spec §九）：内部 judge 的结论 vs 机械判定，批跑的副产物。

能机械核对的只有两层——run 层（总目标就是样本目标）与目标局 episode 层（派给样本目标的最后一局）。
task 层的判据是拆解器当场写的，没有机械对照，只统计终止类别分布。

`judge_agreement_scorer` 把四格结论包成统一 Scorer（spec2 §六取舍 B：e2e task 的附加 scorer）。
"""

from __future__ import annotations

from collections import Counter

from evals.core import Score, Scorer, mechanical_scorer
from evals.schema import EvalSample, JudgeCell, JudgeCellName, Outcome
from evals.scorers import RunStream
from pokemon_agent.direct.trace.content import TaskEndContent
from pokemon_agent.schemas.harness import TraceKind

_DONE = "goal_done"


def judge_agreement_scorer() -> Scorer:
    """judge 一致性的**附加 scorer**（spec2 §六取舍 B）：四格结论进 Score 的 detail 分列。

    机械结论内部现算（与 `red_line_scorer` 同一手法——判据是纯函数，重算无副作用）。
    """

    def score(stream: RunStream, sample: EvalSample) -> Score:
        mech = mechanical_scorer()(stream, sample)
        assert mech.outcome is not None
        cells = judge_cells(stream, sample.sample_id, mech.outcome)
        return Score(
            scorer_id="judge_agreement",
            outcome=mech.outcome,
            sample_id=sample.sample_id,
            detail={"cells": [c.model_dump() for c in cells]},
        )

    return score


def judge_cells(stream: RunStream, goal_id: str, mech: Outcome) -> list[JudgeCell]:
    """run 层与目标局 episode 层各一格；该层没有收尾账时不出格。

    `mech` 是机械判定的结论（统一 Scorer 的机械 `Score.outcome`）——本模块不认识
    `CheckVerdict`，判定货币的收敛边界在 report/evaluate 的报告投影（328）。
    """
    cells: list[JudgeCell] = []
    end = stream.run_end()
    if end is not None:
        cells.append(_cell("run", end.termination == _DONE, mech))
    episodes = stream.episodes_for(goal_id)
    last = stream.episode_end(episodes[-1]) if episodes else None
    if last is not None:
        cells.append(_cell("episode", last.termination == _DONE, mech))
    return cells


def _cell(layer: str, judge_done: bool, mech: Outcome) -> JudgeCell:
    """一格。"""
    name: JudgeCellName
    if mech == "unjudgeable":
        name = "n/a"
    elif judge_done:
        name = "TP" if mech == "pass" else "FP"
    else:
        name = "FN" if mech == "pass" else "TN"
    return JudgeCell(layer=layer, judge_done=judge_done, mech=mech, cell=name)  # type: ignore[arg-type]


def task_terminations(stream: RunStream, goal_id: str) -> dict[str, int]:
    """目标那几局里 task 层 judge 的终止类别分布。"""
    counts: Counter[str] = Counter()
    for e in stream.in_episodes(stream.episodes_for(goal_id), TraceKind.TASK_END):
        assert isinstance(e.content, TaskEndContent)
        counts[e.content.termination] += 1
    return dict(counts)


__all__ = ["judge_cells", "task_terminations"]
