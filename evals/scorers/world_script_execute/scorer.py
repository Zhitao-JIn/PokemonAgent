"""scripts 测评的 scorer：`judge_case` 纯函数判两面，`script_scorer` 把结论翻成 inspect Score。

两面分列（Score 的 value 是 dict，各出一列指标）：
- `code`：脚本自报的 ok / code / data / events 是否符合期望；
- `truth`：前后两帧 RAM 档观测的取值与差值是否符合期望（独立真值，不信自述）；
- `pass`：两面都过。
"""

from __future__ import annotations

from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    Score,
    Scorer,
    Target,
    accuracy,
    grouped,
    scorer,
    stderr,
)
from inspect_ai.solver import TaskState
from inspect_ai.util import store_as

from evals.dataset.world_script_execute import ScriptCase, ScriptExpect
from evals.dataset.world_script_execute.schemas import BAG_PREFIX
from evals.solvers.world_script_execute import (
    ScriptReport,
    ScriptRun,
    ScriptRunRecord,
)
from pokemon_agent.world import RamReadout, TaskObservation
from pokemon_agent.world.items import item_name

from .takeover_checks import judge_takeover
from .verdict import ScriptVerdict


def probe(observation: TaskObservation, ram: RamReadout, key: str) -> str | int:
    """按真值词表从一帧里取值（词表见 `schemas.PROBE_KEYS`）。

    前置条件：`key` 在词表里（`ScriptExpect` 构造时已校验）。
    """
    if key.startswith(BAG_PREFIX):
        name = key.removeprefix(BAG_PREFIX)
        return sum(b.quantity for b in ram.bag if item_name(b.item_id) == name)
    place = observation.place
    assert place is not None, "task 档观测必带坐标"
    values: dict[str, str | int] = {
        "map_id": place.map_id,
        "x": place.x,
        "y": place.y,
        "facing": observation.facts.facing,
        "scene": str(observation.scene),
        "money": ram.money,
        "party_hp_missing": sum(m.max_hp - m.hp for m in ram.party),
    }
    assert key in values, f"真值键 {key!r} 不在词表里"
    return values[key]


def judge_case(case: ScriptCase, run: ScriptRun) -> ScriptVerdict:
    """判一条用例：自报面看报告，真值面看前后两帧。脚本崩溃时自报面直接判负。"""
    expect = case.expect
    if expect.status is not None:
        return judge_takeover(expect, run)
    code = [f"脚本抛异常：{run.crash}"] if run.report is None else _judge_report(expect, run.report)
    return ScriptVerdict(code_problems=code, truth_problems=_judge_truth(expect, run))


def _judge_report(expect: ScriptExpect, report: ScriptReport) -> list[str]:
    """自报面：ok / code / data 子集 / events 子序列 / 对话片段。"""
    problems: list[str] = []
    if report.ok is not expect.ok:
        problems.append(f"ok={report.ok}，期望 {expect.ok}")
    if report.code != expect.code:
        problems.append(f"code={report.code}，期望 {expect.code}")
    for key, want in expect.data.items():
        got = report.data.get(key)
        if got != want:
            problems.append(f"data.{key}={got!r}，期望 {want!r}")
    outcomes = iter(e.outcome for e in report.events)
    if not all(want in outcomes for want in expect.events):
        got = [e.outcome for e in report.events]
        problems.append(f"events={got}，期望按序含 {expect.events}")
    said = " ".join(e.text or "" for e in report.events if e.outcome == "dialog")
    problems += [f"对话里没有 {want!r}" for want in expect.dialog if want not in said]
    return problems


def _judge_truth(expect: ScriptExpect, run: ScriptRun) -> list[str]:
    """真值面：收尾帧取值 + 前后差值。"""
    after = (run.after_observation, run.after_ram)
    before = (run.before_observation, run.before_ram)
    problems: list[str] = []
    for key, want in expect.after.items():
        got = probe(*after, key)
        if got != want:
            problems.append(f"收尾 {key}={got!r}，期望 {want!r}")
    for key, want in expect.delta.items():
        start, end = probe(*before, key), probe(*after, key)
        assert isinstance(start, int) and isinstance(end, int), f"{key} 不是整数量，不能求差"
        if end - start != want:
            problems.append(f"{key} 变化 {end - start}（{start}→{end}），期望 {want}")
    return problems


@scorer(
    metrics={
        "pass": [accuracy(), stderr(), grouped(accuracy(), "script")],
        "code": [accuracy()],
        "truth": [accuracy()],
    }
)
def script_scorer() -> Scorer:
    """把 `judge_case` 的结论翻成 inspect Score（三列：pass / code / truth）。

    前置条件：solver 已把 `ScriptRun` 写进 store（没写说明 solver 没跑完，是 bug）。
    """

    async def score(state: TaskState, target: Target) -> Score:
        del target  # 期望在 metadata 的用例里，target 只给 View 展示期望结局码
        run = store_as(ScriptRunRecord).run
        assert run is not None, "solver 没有写 ScriptRun"
        case = ScriptCase.model_validate(state.metadata["case"])
        verdict = judge_case(case, run)
        mark = {True: CORRECT, False: INCORRECT}
        return Score(
            value={
                "pass": mark[verdict.passed],
                "code": mark[not verdict.code_problems],
                "truth": mark[not verdict.truth_problems],
            },
            answer=run.report.code if run.report else "crash",
            explanation="；".join([*verdict.code_problems, *verdict.truth_problems]) or "全部符合",
            metadata={
                "verdict": verdict.model_dump(),
                "report": run.report.model_dump(mode="json") if run.report else None,
                "crash": run.crash,
                "seconds": run.seconds,
            },
        )

    return score


__all__ = ["judge_case", "probe", "script_scorer"]
