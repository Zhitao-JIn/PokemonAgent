"""judge 过程集（spec §九）：内部 judge 的结论 vs 机械判定，批跑的副产物。

能机械核对的只有两层——run 层（总目标就是样本目标）与目标局 episode 层（派给样本目标的最后一局）。
task 层的判据是拆解器当场写的，没有机械对照，只统计终止类别分布。
"""

from __future__ import annotations

from collections import Counter

from evals.e2e.checks import RunStream
from evals.e2e.schemas import CheckVerdict, JudgeCell, JudgeCellName, Outcome
from pokemon_agent.schemas.harness import TraceKind
from pokemon_agent.tools.trace.content import TaskEndContent

_DONE = "goal_done"


def judge_cells(stream: RunStream, goal_id: str, verdict: CheckVerdict) -> list[JudgeCell]:
    """run 层与目标局 episode 层各一格；该层没有收尾账时不出格。"""
    cells: list[JudgeCell] = []
    end = stream.run_end()
    if end is not None:
        cells.append(_cell("run", end.termination == _DONE, verdict.outcome))
    episodes = stream.episodes_for(goal_id)
    last = stream.episode_end(episodes[-1]) if episodes else None
    if last is not None:
        cells.append(_cell("episode", last.termination == _DONE, verdict.outcome))
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
