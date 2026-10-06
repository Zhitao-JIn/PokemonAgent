"""跑宏测评：每个用例从存档起一个 world、按开跑前的键、调宏、核对，写结果与报告。"""

from __future__ import annotations

import json
import time
from pathlib import Path

from pokemon_agent.world.pyboy_world import PyBoyWorld

from .cases import CASES, Case

REPO_ROOT = Path(__file__).resolve().parents[2]
ROM = REPO_ROOT / "assets" / "rom"
STATES = REPO_ROOT / "experiment" / "experiment_states"
RESULTS_ROOT = REPO_ROOT / "eval_results" / "macros"
RESULTS, REPORT = "results.jsonl", "report.md"


class _NoVision:
    """宏测评只走 task 档感知，不该有任何视觉调用。"""

    def describe(self, req: object) -> object:
        raise AssertionError("宏测评不该调视觉模型")


def run_case(case: Case) -> dict[str, object]:
    """跑一个用例，返回一行结果（`problems` 为空即通过）。

    步骤 1：从存档起 world，按开跑前的键。
    步骤 2：记开跑前一帧，调宏，记收尾一帧。
    步骤 3：核对结局、原因码与各项状态变化。
    """
    # 步骤 1。
    world = PyBoyWorld(str(ROM), _NoVision(), state_path=str(STATES / case.state))  # type: ignore[arg-type]
    world.reset(task_id=case.case_id, goal="宏测评", success_criteria="-", max_steps=1)
    for key in case.pre:
        world.step([(key, 1)], settle=True)

    # 步骤 2。
    before = world.perceive_task().observation
    started = time.time()
    outcome = world.run_macro(case.macro, dict(case.args))
    seconds = round(time.time() - started, 2)
    after = world.perceive_task().observation

    # 步骤 3。
    problems: list[str] = []
    if outcome.status is not case.status:
        problems.append(f"结局 {outcome.status.value}，期望 {case.status.value}")
    if outcome.reason_code is not case.reason:
        want = case.reason.value if case.reason else "无"
        got = outcome.reason_code.value if outcome.reason_code else "无"
        problems.append(f"原因码 {got}，期望 {want}")
    if case.summary and case.summary not in outcome.summary:
        problems.append(f"摘要里没有 {case.summary!r}")
    for check in case.checks:
        try:
            problem = check(before, after)
        except AssertionError as exc:
            problem = str(exc)
        if problem:
            problems.append(problem)
    return {
        "case_id": case.case_id,
        "passed": not problems,
        "problems": problems,
        "before_scene": before.scene.value,
        "after_scene": after.scene.value,
        "outcome": outcome.model_dump(mode="json"),
        "seconds": seconds,
    }


def run_suite(case_ids: list[str] | None = None) -> Path:
    """跑一批用例，落 `results.jsonl` 与 `report.md`，返回报告目录。"""
    chosen = [c for c in CASES if case_ids is None or c.case_id in case_ids]
    assert chosen, f"没有匹配的用例：{case_ids}"
    report_dir = RESULTS_ROOT / time.strftime("%Y%m%d-%H%M%S")
    report_dir.mkdir(parents=True, exist_ok=True)
    rows = [run_case(case) for case in chosen]
    with (report_dir / RESULTS).open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    (report_dir / REPORT).write_text(render_report(rows), encoding="utf-8")
    return report_dir


def render_report(rows: list[dict[str, object]]) -> str:
    """一张表：用例、通过与否、结局、摘要或原因、问题。"""
    passed = sum(1 for r in rows if r["passed"])
    lines = [
        f"# 宏测评：{passed}/{len(rows)} 通过",
        "",
        "| 用例 | 通过 | 结局 | 摘要 / 原因 | 步数 | 秒 | 问题 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        o = r["outcome"]
        assert isinstance(o, dict)
        detail = o["summary"] or o["reason"]
        problems = "；".join(r["problems"]) or ""  # type: ignore[arg-type]
        lines.append(
            f"| {r['case_id']} | {'✅' if r['passed'] else '❌'} | {o['status']} | {detail} "
            f"| {len(o['steps'])} | {r['seconds']} | {problems} |"
        )
    return "\n".join(lines) + "\n"


__all__ = ["render_report", "run_case", "run_suite"]
