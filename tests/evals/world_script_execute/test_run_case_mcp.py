"""run_case 在假世界上：脚本信封映射、server 侧异常、租约归还失败不掩盖结论。"""

from __future__ import annotations

from pathlib import Path

import pytest
from _doubles.script_frames import frame

from evals.world_script_execute import solver
from evals.world_script_execute.dataset.schemas import ScriptCase, ScriptExpect
from pokemon_agent.mcpclient.client import McpToolError
from pokemon_agent.world import Facts, PlaceInWorld, StepObservation, TaskScene


def _case() -> ScriptCase:
    return ScriptCase(
        case_id="demo",
        script="walk_to_adjacent",
        state="knowledge/knowledge_movement_obstacle.state",
        expect=ScriptExpect(ok=True, code="ok", after={"x": 8}),
        basis="示范",
    )


class _FakeWorld:
    """带 `call_script` / `perceive_task` / `release_lease` 的最小世界。"""

    client_id = "eval"

    def __init__(self, envelope: dict, release_raises: Exception | None = None) -> None:
        self.envelope = envelope
        self.release_raises = release_raises
        self.script_calls: list[tuple[str, dict]] = []

    def call_script(self, name: str, args: dict) -> dict:
        self.script_calls.append((name, args))
        return self.envelope

    def release_lease(self) -> None:
        if self.release_raises is not None:
            raise self.release_raises


def test_run_case_maps_script_envelope_to_report(monkeypatch: pytest.MonkeyPatch) -> None:
    """信封 observations 映入报告；历史顶层 events 不进入新报告。"""
    observation = StepObservation(
        step=1,
        place=PlaceInWorld(map_id=12, x=9, y=12),
        facing="south",
        scene=TaskScene.WALK,
        overlay=Facts.Overlay.DIALOG,
        dialog_text="Hello.",
    )
    envelope = {
        "ok": False,
        "code": "blocked",
        "data": {
            "ok": False,
            "code": "blocked",
            "calls": [1, 2],
            "entered_grass": False,
            "observations": [observation.model_dump(mode="json")],
        },
        "events": [{"outcome": "legacy_event_must_be_ignored"}],
    }
    world = _FakeWorld(envelope)
    monkeypatch.setattr(solver, "state_path", lambda state, version="v1": Path(state))
    monkeypatch.setattr(solver, "start_world", lambda *a, **k: world)
    monkeypatch.setattr(solver, "read_frame", lambda w: frame())

    run = solver.run_case(_case())

    assert run.crash == ""
    assert run.report is not None
    assert run.report.ok is False
    assert run.report.code == "blocked"
    assert run.report.data == {"entered_grass": False}
    assert run.report.observations == [observation]
    assert not hasattr(run.report, "events")
    assert world.script_calls == [("walk_to_adjacent", {})]


def test_run_case_records_server_side_exception_as_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """server 侧异常 → report 为 None、crash 非空。"""

    class RaisingWorld(_FakeWorld):
        def call_script(self, name: str, args: dict) -> dict:
            raise McpToolError("server boom")

    world = RaisingWorld({"ok": True, "code": "ok", "data": {}})
    monkeypatch.setattr(solver, "state_path", lambda state, version="v1": Path(state))
    monkeypatch.setattr(solver, "start_world", lambda *a, **k: world)
    monkeypatch.setattr(solver, "read_frame", lambda w: frame())

    run = solver.run_case(_case())

    assert run.report is None
    assert run.crash == "McpToolError: server boom"


def test_run_case_keeps_report_when_release_lease_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stop_world 抛错不得掩盖脚本结论。"""
    envelope = {
        "ok": True,
        "code": "ok",
        "data": {"ok": True, "code": "ok", "calls": [], "observations": []},
    }
    world = _FakeWorld(envelope, release_raises=RuntimeError("lease fail"))
    monkeypatch.setattr(solver, "state_path", lambda state, version="v1": Path(state))
    monkeypatch.setattr(solver, "start_world", lambda *a, **k: world)
    monkeypatch.setattr(solver, "read_frame", lambda w: frame())

    run = solver.run_case(_case())

    assert run.report is not None and run.report.ok is True
    assert run.crash == ""
