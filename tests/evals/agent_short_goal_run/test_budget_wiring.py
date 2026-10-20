"""短目标评测的预算文件从 task 原样传到装配点。"""

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from inspect_ai.solver import TaskState
from pydantic import ValidationError

from evals.agent_short_goal_run.dataset.loader import load_samples
from evals.agent_short_goal_run.solver.record import RunOneRequest
from evals.agent_short_goal_run.solver.solver import run_one_solver
from evals.agent_short_goal_run.solver.worker import _execute
from evals.agent_short_goal_run.task import agent_short_goal_run, write_run_config
from evals.runconfig import load_config
from pokemon_agent.run_config import load_run_config
from pokemon_agent.schemas.harness.domain import RunResult

SAMPLE_ID = "knowledge_door_transition"


def test_task_writes_exact_budget_bytes_and_matching_context(tmp_path, monkeypatch):
    monkeypatch.setattr("evals.agent_short_goal_run.task.load_env_file", lambda: None)
    cfg = load_config()

    task = agent_short_goal_run(
        samples=[SAMPLE_ID], log_dir=str(tmp_path), grader_model=None, transcript=False
    )

    path = tmp_path / "run_config.json"
    raw = (json.dumps({"budget": cfg["budget"]}, ensure_ascii=False, indent=2) + "\n").encode()
    context = json.loads((tmp_path / "baseline_context.json").read_text(encoding="utf-8"))
    budget = load_run_config(path).budget
    assert path.read_bytes() == raw
    assert context["run_config_path"] == str(path)
    assert context["run_config_sha256"] == hashlib.sha256(raw).hexdigest()
    assert task.metadata["run_config_sha256"] == context["run_config_sha256"]
    assert (budget.wall_clock_s, budget.max_episodes, budget.max_total_actions) == (600, 3, 60)
    assert (budget.reserve_s, budget.episode_max_tasks, budget.max_decompositions) == (60, 6, 12)
    assert (budget.task_max_steps, budget.min_request_s) == (12, 3)
    assert (budget.plan_thinking, budget.plan_max_tokens, budget.plan_timeout_s) == (
        False,
        4096,
        45,
    )


def test_unknown_budget_field_is_rejected_before_worker_starts(tmp_path):
    with pytest.raises(ValidationError):
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
        tmp_path, {"wall_clock_s": 600, "max_episodes": 3, "max_total_actions": 60}
    )
    sample = next(s for s in load_samples() if s.sample_id == SAMPLE_ID)
    seen = []

    real_load = assembly.load_run_config

    def checked_load(config):
        config_path = Path(config)
        seen.append((config_path, hashlib.sha256(config_path.read_bytes()).hexdigest()))
        return real_load(config_path)

    def fake_restore(manifest, build_branch, sample_id):
        deps = build_branch("main")
        assert (
            deps.budget.wall_clock_s,
            deps.budget.max_episodes,
            deps.budget.max_total_actions,
        ) == (
            600,
            3,
            60,
        )
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
                "task_summarizer",
            )
        }
    )
    monkeypatch.setattr(assembly, "load_run_config", checked_load)
    monkeypatch.setattr(assembly, "load_env_file", lambda: None)
    monkeypatch.setattr(
        assembly,
        "env_str",
        lambda name: (
            "http://example" if name in {"MCP_MEMORY_SERVER_URL", "MCP_WORLD_SERVER_URL"} else ""
        ),
    )
    monkeypatch.setattr(assembly, "assert_mcp_server_ready", lambda *args: {})
    monkeypatch.setattr(
        assembly.WorldMcpTool,
        "build",
        lambda *args, **kwargs: SimpleNamespace(release_lease=lambda: None),
    )
    monkeypatch.setattr(assembly.MemoryTool, "build", lambda **kwargs: object())
    monkeypatch.setattr(assembly.TraceTool, "build", lambda **kwargs: object())
    monkeypatch.setattr(assembly.BrainTool, "build", lambda **kwargs: tools)
    monkeypatch.setattr(assembly, "CHECKPOINT_ENABLED", False)
    monkeypatch.setattr(assembly, "build_saver", lambda root: None)
    monkeypatch.setattr(assembly, "compile_task_graph", lambda: None)
    monkeypatch.setattr(assembly, "compile_episode_graph", lambda: None)
    monkeypatch.setattr(assembly, "compile_run_graph", lambda **kwargs: None)
    monkeypatch.setattr(runner, "_load_env", lambda path: None)
    monkeypatch.setattr(runner, "prepare_archive", lambda sample, work: "manifest")
    monkeypatch.setattr(runner, "restore_run", fake_restore)

    runner.run_one(sample, tmp_path / "sample", {}, run_config_path=str(path))

    assert seen == [(path, digest)]
