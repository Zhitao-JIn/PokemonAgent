"""短目标评测的配置覆盖文件从 task 原样传到装配点。"""

import asyncio
import hashlib
import json
import subprocess
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
from evals.runconfig import load_config
from pokemon_agent.schemas.harness.domain import RunResult
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
        False,
        4096,
        45,
    )
    assert app.models.text.model == cfg["models"]["text_model"]


def test_unknown_budget_field_is_rejected_before_worker_starts(tmp_path):
    with pytest.raises(ConfigValidationError):
        write_run_config(tmp_path, {"unexpected": 1})


def test_solver_request_carries_the_config_file_path(tmp_path, monkeypatch):
    captured = []

    def fake_subprocess(*args, **kwargs):
        captured.append(RunOneRequest.model_validate_json(kwargs["input"]))
        return subprocess.CompletedProcess(args, 0)

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

    assert len(captured) == 1
    assert captured[0].run_config_path == path


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

    def fake_restore(manifest, build_branch, sample_id):
        deps = build_branch("main")
        budget = deps.config.budget
        assert (budget.wall_clock_s, budget.max_episodes, budget.max_total_actions) == (600, 3, 60)
        assert deps.config.run.run_id == f"eval-{SAMPLE_ID}"
        return RunResult(run_id="r1", sample_id=sample_id, branch="main")

    tools = SimpleNamespace(
        **{
            name: object()
            for name in (
                "chooser",
                "judger",
                "planner",
                "reflector",
                "verifier",
                "decomposer",
                "summarizer",
                "run_summarizer",
                "task_summarizer",
            )
        }
    )
    monkeypatch.setenv("MCP_MEMORY_SERVER_URL", "http://example")
    monkeypatch.setenv("MCP_WORLD_SERVER_URL", "http://example")
    monkeypatch.setattr(assembly, "load_config", checked_load)
    monkeypatch.setattr(assembly, "load_env_file", lambda: None)
    monkeypatch.setattr(assembly, "assert_mcp_server_ready", lambda *args: {})
    monkeypatch.setattr(
        assembly.WorldMcpTool,
        "build",
        lambda *args, **kwargs: SimpleNamespace(release_lease=lambda: None),
    )
    monkeypatch.setattr(assembly.MemoryTool, "build", lambda **kwargs: object())
    monkeypatch.setattr(assembly.TraceTool, "build", lambda **kwargs: object())
    monkeypatch.setattr(assembly.BrainTool, "build", lambda **kwargs: tools)
    monkeypatch.setattr(assembly, "build_saver", lambda root: None)
    monkeypatch.setattr(assembly, "compile_task_graph", lambda: None)
    monkeypatch.setattr(assembly, "compile_episode_graph", lambda: None)
    monkeypatch.setattr(assembly, "compile_run_graph", lambda **kwargs: None)
    monkeypatch.setattr(runner, "load_env_file", lambda path: None)
    monkeypatch.setattr(runner, "prepare_archive", lambda sample, work: "manifest")
    monkeypatch.setattr(runner, "restore_run", fake_restore)

    runner.run_one(sample, tmp_path / "sample", run_config_path=str(path))

    assert seen == [(path, digest, 2)]
