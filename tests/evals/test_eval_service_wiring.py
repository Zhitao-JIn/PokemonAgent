"""三个评测调用点把服务生命周期绑定到样本或评测运行。"""

from __future__ import annotations

import asyncio
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest
from _doubles.script_frames import frame, run_of
from inspect_ai.solver import TaskState

from evals.agent_short_goal_run.solver.solver import run_one_solver
from evals.world_script_execute import isolated
from evals.world_script_execute.dataset.schemas import ScriptCase, ScriptExpect
from evals.world_script_execute.solver import ScriptRun


def _task_state(sample_id: str) -> TaskState:
    return TaskState(
        model="none",
        sample_id=sample_id,
        epoch=1,
        input="run",
        messages=[],
        metadata={"sample_id": sample_id, "dataset_version": "v1"},
    )


def _script_case() -> ScriptCase:
    return ScriptCase(
        case_id="demo",
        script="walk_to_adjacent",
        state="knowledge/knowledge_movement_obstacle.state",
        expect=ScriptExpect(ok=True, code="ok", after={"x": 8}),
        basis="示范",
    )


@pytest.mark.parametrize("outcome", ["timeout", "error"])
def test_short_goal_closes_services_after_worker_error_or_timeout(
    monkeypatch, tmp_path, outcome
) -> None:
    events = []

    def fake_services(**options):
        class FakeServices:
            def __enter__(self):
                events.append(("enter", options))
                return {
                    "MCP_WORLD_SERVER_URL": "http://world.fake",
                    "MCP_MEMORY_SERVER_URL": "http://memory.fake",
                }

            def __exit__(self, exc_type, exc, traceback):
                events.append(("exit",))
                return False

        return FakeServices()

    def fake_subprocess(*args, **kwargs):
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])
        raise RuntimeError("worker failed")

    monkeypatch.setattr("evals.agent_short_goal_run.solver.solver.eval_services", fake_services)
    monkeypatch.setattr(subprocess, "run", fake_subprocess)
    solve = run_one_solver(
        report_dir=str(tmp_path / outcome),
        run_config_path="config.json",
        models={},
        timeout=12,
        transcript=False,
    )

    if outcome == "timeout":
        result = asyncio.run(solve(_task_state(f"sample-{outcome}"), None))
        assert result.output.completion == "timeout"
    else:
        with pytest.raises(RuntimeError, match="worker failed"):
            asyncio.run(solve(_task_state(f"sample-{outcome}"), None))
    assert events[0] == (
        "enter",
        {
            "world": True,
            "memory": True,
            "knowledge_source": Path.cwd() / "memory" / "knowledge_memory",
            "admin": True,
            "export_env": False,
        },
    )
    assert events[-1] == ("exit",)


def test_concurrent_short_goal_samples_receive_distinct_service_environments(
    monkeypatch, tmp_path
) -> None:
    lock = threading.Lock()
    barrier = threading.Barrier(2)
    sequence = iter((1, 2))
    captured = []
    events = []

    @contextmanager
    def fake_services(**options):
        with lock:
            index = next(sequence)
        environment = {
            "MCP_WORLD_SERVER_URL": f"http://world.fake:{index}",
            "MCP_MEMORY_SERVER_URL": f"http://memory.fake:{index}",
        }
        events.append(("enter", options, environment))
        try:
            yield environment
        finally:
            events.append(("exit", environment))

    def fake_subprocess(*args, **kwargs):
        captured.append(kwargs["env"])
        barrier.wait(timeout=5)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr("evals.agent_short_goal_run.solver.solver.eval_services", fake_services)
    monkeypatch.setattr(subprocess, "run", fake_subprocess)
    solve = run_one_solver(
        report_dir=str(tmp_path),
        run_config_path="config.json",
        models={},
        timeout=12,
        transcript=False,
    )

    async def run_both() -> None:
        await asyncio.gather(
            solve(_task_state("sample-a"), None),
            solve(_task_state("sample-b"), None),
        )

    asyncio.run(run_both())

    assert len(captured) == 2
    assert {item["MCP_WORLD_SERVER_URL"] for item in captured} == {
        "http://world.fake:1",
        "http://world.fake:2",
    }
    assert {item["MCP_MEMORY_SERVER_URL"] for item in captured} == {
        "http://memory.fake:1",
        "http://memory.fake:2",
    }
    assert len([event for event in events if event[0] == "enter"]) == 2
    assert len([event for event in events if event[0] == "exit"]) == 2


@pytest.mark.parametrize("outcome", ["success", "timeout", "worker_error"])
def test_world_case_caller_closes_world_service_after_each_worker_outcome(
    monkeypatch, tmp_path, outcome
) -> None:
    events = []

    @contextmanager
    def fake_services(**options):
        events.append(("enter", options))
        try:
            yield {"MCP_WORLD_SERVER_URL": "http://world.fake"}
        finally:
            events.append(("exit",))

    def fake_subprocess(arguments, **kwargs):
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(arguments, kwargs["timeout"])
        if outcome == "worker_error":
            return subprocess.CompletedProcess(arguments, 1, stderr="failed")
        request = isolated.ScriptRequest.model_validate_json(kwargs["input"])
        before = frame()
        request.output.write_text(
            run_of(None, before, before, crash="worker result").model_dump_json(),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(arguments, 0, stderr="")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(isolated, "eval_services", fake_services)
    monkeypatch.setattr(isolated.subprocess, "run", fake_subprocess)

    if outcome == "timeout":
        with pytest.raises(isolated.ScriptSetupTimeout):
            isolated.run_isolated(_script_case(), timeout=1)
    elif outcome == "worker_error":
        with pytest.raises(isolated.ScriptWorkerFailure, match="failed"):
            isolated.run_isolated(_script_case(), timeout=1)
    else:
        result: ScriptRun = isolated.run_isolated(_script_case(), timeout=1)
        assert result.crash == "worker result"

    assert events == [
        ("enter", {"world": True, "memory": False}),
        ("exit",),
    ]
