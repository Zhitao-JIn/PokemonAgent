"""跑接管视图测评：每个用例从存档起一个 world、按开跑前的键、取一帧，逐字段比视图，写结果与报告。"""

from __future__ import annotations

import json
import time
from pathlib import Path

from pokemon_agent.world.pyboy_world import PyBoyWorld

from .cases import CASES, ViewCase

REPO_ROOT = Path(__file__).resolve().parents[2]
ROM = REPO_ROOT / "assets" / "rom"
STATES = REPO_ROOT / "experiment" / "experiment_states"
RESULTS_ROOT = REPO_ROOT / "eval_results" / "views"
RESULTS, REPORT = "results.jsonl", "report.md"
_MISSING = object()


class _NoVision:
    """视图测评只走 task 档感知，不该有任何视觉调用。"""

    def describe(self, req: object) -> object:
        raise AssertionError("视图测评不该调视觉模型")


def run_case(case: ViewCase) -> dict[str, object]:
    """跑一个用例，返回一行结果（`problems` 为空即通过）。"""
    world = PyBoyWorld(str(ROM), _NoVision(), state_path=str(STATES / case.state))  # type: ignore[arg-type]
    world.reset(task_id=case.case_id, goal="视图测评", success_criteria="-", max_steps=1)
    for key in case.pre:
        world.step([(key, 1)], settle=True)
    obs = world.perceive_task().observation
    problems: list[str] = []
    if obs.scene is not case.scene:
        problems.append(f"场合 {obs.scene.value}，期望 {case.scene.value}")
    view = obs.takeover.model_dump(mode="json") if obs.takeover is not None else None
    if view is None:
        problems.append("没有视图")
    else:
        for path, want in case.expect.items():
            got = _get(view, path)
            if got is _MISSING:
                problems.append(f"{path} 缺失，期望 {want!r}")
            elif got != want:
                problems.append(f"{path} = {got!r}，期望 {want!r}")
    problems += [f"屏上没有 {s!r}" for s in case.on_screen if s not in obs.facts.screen]
    return {"case_id": case.case_id, "passed": not problems, "problems": problems, "view": view}


def _get(data: object, path: str) -> object:
    """点路径取值（数字段当列表下标）；取不到返回 `_MISSING`。"""
    for part in path.split("."):
        if isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        elif isinstance(data, dict) and part in data:
            data = data[part]
        else:
            return _MISSING
    return data


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
    passed = sum(1 for r in rows if r["passed"])
    lines = [
        f"# 接管视图测评：{passed}/{len(rows)} 通过",
        "",
        "| 用例 | 通过 | 问题 |",
        "|---|---|---|",
    ]
    lines += [
        f"| {r['case_id']} | {'✅' if r['passed'] else '❌'} | {'；'.join(r['problems'])} |"  # type: ignore[arg-type]
        for r in rows
    ]
    (report_dir / REPORT).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_dir


__all__ = ["run_case", "run_suite"]
