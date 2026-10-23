"""短目标评测的配置覆盖文件从 task 原样传到装配点。"""

import asyncio
import hashlib
import json
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from inspect_ai.solver import TaskState

from evals.agent_short_goal_run.dataset.loader import load_samples
from evals.agent_short_goal_run.solver.record import RunOneRequest
from evals.agent_short_goal_run.solver.solver import run_one_solver
from evals.agent_short_goal_run.solver.worker import _execute
from evals.agent_short_goal_run.task import agent_short_goal_run, write_run_config
from evals.common.overlay import eval_overlay
from evals.paths import REPO_ROOT
from evals.runconfig import load_config
from pokemon_agent.settings import ConfigValidationError
from pokemon_agent.settings import load_config as load_app_config

SAMPLE_ID = "knowledge_door_transition"


def test_task_writes_exact_overlay_bytes_and_matching_context(tmp_path, monkeypatch):
    monkeypatch.setattr("evals.agent_short_goal_run.task.load_env_file", lambda: None)
    cfg = load_config()

    task = agent_short_goal_run(
        samples=[SAMPLE_ID], log_dir=str(tmp_path), grader_model=None, transcript=False
    )

    path = tmp_path / "run_config.json"
    overlay = eval_overlay({**cfg, "trace_backend": cfg.get("trace_backend", "local")})
    raw = (json.dumps(overlay, ensure_ascii=False, indent=2) + "\n").encode()
    context = json.loads((tmp_path / "baseline_context.json").read_text(encoding="utf-8"))
    app = load_app_config(path).config
    budget = app.budget
    assert path.read_bytes() == raw
    assert context["run_config_path"] == str(path)
    assert context["run_config_sha256"] == hashlib.sha256(raw).hexdigest()
    assert task.metadata["run_config_sha256"] == context["run_config_sha256"]
    assert (budget.wall_clock_s, budget.max_episodes, budget.max_total_actions) == (600, 3, 60)
    assert (budget.reserve_s, budget.episode_max_tasks, budget.max_decompositions) == (60, 6, 12)
    assert (budget.task_max_steps, budget.min_request_s) == (12, 3)
    assert (app.models.plan.thinking, app.models.plan.max_tokens, app.models.plan.timeout_s) == (
        True,
        25600,
        90,
    )
    assert app.models.text.model == cfg["models"]["text_model"]


def test_unknown_budget_field_is_rejected_before_worker_starts(tmp_path):
    with pytest.raises(ConfigValidationError):
        write_run_config(tmp_path, {"unexpected": 1})


def test_solver_request_carries_the_config_file_path(tmp_path, monkeypatch):
    captured = []
    service_events = []

    @contextmanager
    def fake_services(**options):
        service_events.append(("enter", options))
        try:
            yield {
                "MCP_WORLD_SERVER_URL": "http://world.fake:41001",
                "MCP_MEMORY_SERVER_URL": "http://memory.fake:41002",
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            }
        finally:
            service_events.append(("exit",))

    def fake_subprocess(*args, **kwargs):
        captured.append(RunOneRequest.model_validate_json(kwargs["input"]))
        captured.append(kwargs["env"])
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr("evals.agent_short_goal_run.solver.solver.eval_services", fake_services)
    monkeypatch.setattr(subprocess, "run", fake_subprocess)
    state = TaskState(
        model="none",
        sample_id=SAMPLE_ID,
        epoch=1,
        input="run",
        messages=[],
        metadata={"sample_id": SAMPLE_ID, "dataset_version": "v1"},
    )
    path = str(tmp_path / "run_config.json")
    solve = run_one_solver(
        report_dir=str(tmp_path),
        run_config_path=path,
        models={},
        timeout=600,
        transcript=False,
    )

    asyncio.run(solve(state, None))

    assert len(captured) == 2
    assert captured[0].run_config_path == path
    assert captured[1]["MCP_WORLD_SERVER_URL"] == "http://world.fake:41001"
    assert captured[1]["MCP_MEMORY_SERVER_URL"] == "http://memory.fake:41002"
    assert service_events == [
        (
            "enter",
            {
                "world": True,
                "memory": True,
                "knowledge_source": REPO_ROOT / "memory" / "knowledge_memory",
                "admin": True,
                "export_env": False,
            },
        ),
        ("exit",),
    ]


def test_worker_passes_config_path_to_runner(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr(
        "evals.agent_short_goal_run.solver.worker.load_samples",
        lambda version: [SimpleNamespace(sample_id=SAMPLE_ID)],
    )
    monkeypatch.setattr(
        "evals.agent_short_goal_run.solver.runner.run_one",
        lambda *args, **kwargs: captured.append(kwargs),
    )
    path = str(tmp_path / "run_config.json")
    request = RunOneRequest(
        work_dir=str(tmp_path),
        run_config_path=path,
        sample_id=SAMPLE_ID,
        models={},
        trace_backend="local",
        version="v1",
    )

    _execute(RunOneRequest.model_validate_json(request.model_dump_json()))

    assert captured[0]["run_config_path"] == path


def test_runner_reads_the_same_file_through_build_real(tmp_path, monkeypatch):
    import evals.agent_short_goal_run.solver.runner.one as runner
    import pokemon_agent.build as assembly

    path, digest = write_run_config(
        tmp_path,
        {"budget": {"wall_clock_s": 600, "max_episodes": 3, "max_total_actions": 60}},
    )
    sample = next(s for s in load_samples() if s.sample_id == SAMPLE_ID)
    seen = []

    real_load = assembly.load_config

    def checked_load(overlays):
        files = [Path(item) for item in overlays]
        seen.append((files[0], hashlib.sha256(files[0].read_bytes()).hexdigest(), len(files)))
        return real_load(overlays)

    events = []

    class FakeHarness:
        def run(self, run_id, tasks, *, sample_id):
            events.append(("run", run_id, tasks, sample_id))
            return SimpleNamespace(
                model_dump_json=lambda **kwargs: '{"termination":"success"}', branch="main"
            )

    class FakeGame:
        def use_start_state(self, state_path):
            events.append(("state", state_path))

        def release_lease(self):
            events.append(("release",))

    def fake_build_real(*, config):
        app = assembly.load_config(config).config
        budget = app.budget
        assert (budget.wall_clock_s, budget.max_episodes, budget.max_total_actions) == (600, 3, 60)
        assert app.run.run_id == f"eval-{SAMPLE_ID}"
        events.append(("build", config))
        return FakeHarness(), FakeGame()

    monkeypatch.setattr(runner, "build_real", fake_build_real)
    monkeypatch.setattr(assembly, "load_config", checked_load)
    monkeypatch.setattr(runner, "load_env_file", lambda path: None)
    monkeypatch.setattr(runner, "DATASET_DIR", tmp_path / "dataset")
    state_path = tmp_path / "dataset" / sample.dataset_version / sample.start.source_state
    state_path.parent.mkdir(parents=True)
    state_path.write_bytes(b"start")

    runner.run_one(sample, tmp_path / "sample", run_config_path=str(path))

    assert seen == [(path, digest, 2)]
    assert events[0][0] == "build"
    assert events[0][1][0] == str(path)
    assert events[1] == ("state", state_path)
    run_call = events[2]
    assert run_call[0:2] == ("run", f"eval-{SAMPLE_ID}")
    task = run_call[2][0]
    assert (
        task.task_id,
        task.goal,
        task.success_criteria,
        task.max_steps,
        task.initial_state_hint,
    ) == (
        sample.sample_id,
        sample.goal,
        sample.success_criteria,
        sample.max_steps,
        sample.initial_state_hint,
    )
    assert events[-1] == ("release",)
