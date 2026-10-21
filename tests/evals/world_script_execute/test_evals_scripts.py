"""scripts 测评的用法示范：用例怎么写、`judge_case` 怎么判两面（不起模拟器、不调模型）。

真机执行由 world_script_execute task 承载；这里只钉
判定逻辑与用例表自身的契约。
"""

from __future__ import annotations

import pytest
from _doubles.script_frames import frame, run_of
from pydantic import ValidationError

from evals.world_script_execute.compare import judge_case
from evals.world_script_execute.dataset import ScriptCase, ScriptExpect, load
from evals.world_script_execute.dataset.loader import DATASET_DIR, DEFAULT_VERSION
from evals.world_script_execute.solver import (
    ScriptReport,
)
from pokemon_agent.world.scripts.catalog import SCRIPT_FUNCS

STATES = DATASET_DIR / DEFAULT_VERSION / "states"


def case_of(expect: ScriptExpect, script: str = "walk_to_adjacent") -> ScriptCase:
    """一条最小用例。"""
    return ScriptCase(
        case_id="demo", matrix_row=3, script=script, state="s.state", expect=expect, basis="示范"
    )


def test_a_script_that_does_what_it_says_passes_both_sides() -> None:
    case = case_of(ScriptExpect(ok=True, code="ok", data={"entered_grass": False}, after={"x": 8}))
    report = ScriptReport(ok=True, code="ok", data={"entered_grass": False})

    verdict = judge_case(case, run_of(report, frame(), frame(x=8)))

    assert verdict.passed


def test_a_report_claiming_success_is_caught_by_the_ram_truth() -> None:
    case = case_of(
        ScriptExpect(ok=True, code="ok", delta={"money": -1000, "bag:POKé BALL": 5}), "buy_item"
    )
    report = ScriptReport(ok=True, code="ok", data={"spent": 1000})

    verdict = judge_case(case, run_of(report, frame(), frame()))

    assert not verdict.code_problems
    assert verdict.truth_problems == [
        "money 变化 0（3000→3000），期望 -1000",
        "bag:POKé BALL 变化 0（0→0），期望 5",
    ]


def test_a_wrong_result_code_fails_the_report_side_only() -> None:
    case = case_of(ScriptExpect(ok=False, code="blocked", delta={"x": 0, "y": 0}))
    report = ScriptReport(ok=False, code="not_converging")

    verdict = judge_case(case, run_of(report, frame(), frame()))

    assert verdict.code_problems == ["code=not_converging，期望 blocked"]
    assert not verdict.truth_problems


def test_expected_events_must_appear_in_order() -> None:
    case = case_of(ScriptExpect(ok=True, code="ok", events=["dialog", "warp"], delta={"x": 0}))
    out_of_order = ScriptReport.model_validate(
        {"ok": True, "code": "ok", "events": [{"outcome": "warp"}, {"outcome": "dialog"}]}
    )

    verdict = judge_case(case, run_of(out_of_order, frame(), frame()))

    assert verdict.code_problems == ["events=['warp', 'dialog']，期望按序含 ['dialog', 'warp']"]


def test_a_heal_counts_only_if_the_nurse_says_it_is_done() -> None:
    case = case_of(
        ScriptExpect(ok=True, code="ok", dialog=["fighting fit"], after={"party_hp_missing": 0}),
        "heal_at_center",
    )
    report = ScriptReport.model_validate(
        {"ok": True, "code": "ok", "events": [{"outcome": "dialog", "text": "Welcome to our"}]}
    )

    verdict = judge_case(case, run_of(report, frame(), frame()))

    assert verdict.code_problems == ["对话里没有 'fighting fit'"]


def test_a_crashed_script_fails_without_a_report() -> None:
    case = case_of(ScriptExpect(ok=True, code="ok", delta={"x": 0}))

    verdict = judge_case(case, run_of(None, frame(), frame(), crash="KeyError: 'x'"))

    assert verdict.code_problems == ["脚本抛异常：KeyError: 'x'"]


def test_an_expectation_without_any_ram_truth_is_rejected() -> None:
    with pytest.raises(ValidationError, match="至少一项真值期望"):
        ScriptExpect(ok=True, code="ok")


def test_every_case_names_a_real_script_and_an_existing_save_state() -> None:
    unknown = [c.case_id for c in CASES if c.script not in SCRIPT_FUNCS]
    missing = [c.case_id for c in CASES if not (STATES / c.state).is_file()]

    assert unknown == []
    assert missing == []


CASES = [case for case in load() if not case.case_id.startswith("takeover:")]
