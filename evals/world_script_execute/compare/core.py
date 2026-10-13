"""脚本自报与世界真值的纯比较，沿用旧 judge_case 判据。

两面分别返回问题清单：
- `code`：脚本自报的 ok / code / data / events 是否符合期望；
- `truth`：前后两帧 RAM 档观测的取值与差值是否符合期望（独立真值，不信自述）；
- `pass`：两面都过。
"""

from __future__ import annotations

from evals.world_script_execute.dataset import ScriptCase, ScriptExpect
from evals.world_script_execute.dataset.schemas import BAG_PREFIX
from evals.world_script_execute.solver import (
    ScriptReport,
    ScriptRun,
)
from pokemon_agent.world import RamReadout, TaskObservation
from pokemon_agent.world.items import item_name

from .checks import judge_declared_checks
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
    code = [f"脚本抛异常：{run.crash}"] if run.report is None else _judge_report(expect, run.report)
    truth = _judge_truth(expect, run) + judge_declared_checks(expect, run)
    return ScriptVerdict(code_problems=code, truth_problems=truth)


def _judge_report(expect: ScriptExpect, report: ScriptReport) -> list[str]:
    """自报面：ok / code / data 子集 / events 子序列 / 对话片段。"""
    problems: list[str] = []
    if report.ok is not expect.ok:
        problems.append(f"ok={report.ok}，期望 {expect.ok}")
    if report.code != expect.code:
        problems.append(f"code={report.code}，期望 {expect.code}")
    if expect.status is not None and report.data.get("status") != expect.status:
        problems.append(f"status={report.data.get('status')!r}，期望 {expect.status!r}")
    if expect.summary and expect.summary not in str(report.data.get("summary", "")):
        problems.append(f"摘要缺少 {expect.summary!r}")
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
