"""world_script_execute 串行化：build_cases 顺序执行，__main__ 不再接受 --workers。"""

from __future__ import annotations

import sys

import pytest
from _doubles.script_frames import frame, run_of

from evals.world_script_execute.dataset import cases
from evals.world_script_execute.dataset.schemas import ScriptCase, ScriptExpect


def _case(case_id: str) -> ScriptCase:
    return ScriptCase(
        case_id=case_id,
        script="walk_to_adjacent",
        state="s.state",
        expect=ScriptExpect(ok=True, code="ok", after={"x": 8}),
        basis="示范",
    )


def test_build_cases_runs_sequentially_in_input_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """顺序执行，结果顺序与输入一致。"""
    order: list[str] = []

    def fake_run(case: ScriptCase, version: str = "v1"):
        order.append(case.case_id)
        return run_of(None, frame(), frame(), crash="boom")

    monkeypatch.setattr(cases, "run_isolated", fake_run)
    inputs = [_case("a"), _case("b"), _case("c")]

    built = cases.build_cases(inputs, "v1")

    assert order == ["a", "b", "c"]
    assert [test_case.name for test_case in built] == ["a", "b", "c"]


def test_main_no_longer_accepts_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    """传入 --workers 视为参数错误。"""
    from evals.world_script_execute import __main__ as main_mod

    monkeypatch.setattr(sys, "argv", ["evals.world_script_execute", "--workers", "2"])

    with pytest.raises(SystemExit) as exc:
        main_mod.main()

    assert exc.value.code == 2
