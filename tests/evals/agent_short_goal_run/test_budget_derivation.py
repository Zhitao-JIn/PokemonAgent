"""评测样本预算推导与审计字段的合成用法。"""

import asyncio
import json
from contextlib import contextmanager

import pytest
from inspect_ai.solver import TaskState

from evals.agent_short_goal_run.dataset.loader import load
from evals.agent_short_goal_run.solver.record import RunOneRecord
from evals.agent_short_goal_run.solver.runner.one import _record
from evals.agent_short_goal_run.solver.solver import run_one_solver
from evals.agent_short_goal_run.task import agent_short_goal_run
from evals.common.budget import DEFAULTS, derive_sample_budget, sample_timeout
from evals.common.overlay import eval_overlay, sample_overlay, write_overlay
from evals.runconfig import BUDGET_DERIVATION_DEFAULTS, load_config
from pokemon_agent.settings import load_config as load_app_config


def _samples():
    short = load("v20261028_short_frozen")[0]
    mid = next(
        sample for sample in load("v20261028_mid") if sample.sample_id == "mid_heal_buy_return"
    )
    long = load("v20261028_long")[0]
    return short, mid, long


def test_budget_derivation_keeps_short_and_scales_mid_and_long():
    short, mid, long = _samples()
    config = {
        "timeout": 600,
        "budget": {"max_total_actions": 60, "wall_clock_s": 600, "max_episodes": 3},
    }

    assert derive_sample_budget(short, config) == {
        "max_total_actions": 60,
        "wall_clock_s": 600,
        "timeout": 600,
        "max_episodes": 3,
    }
    assert derive_sample_budget(mid, config) == {
        "max_total_actions": 250,
        "wall_clock_s": 10120,
        "timeout": 10420,
        "max_episodes": len(mid.goals),
    }
    assert derive_sample_budget(long, config) == {
        "max_total_actions": 720,
        "wall_clock_s": 28920,
        "timeout": 29220,
        "max_episodes": 6,
    }


def test_budget_derivation_rejects_nonpositive_seconds_per_action():
    _, mid, _ = _samples()
    config = {
        "timeout": 600,
        "budget": {"max_total_actions": 60, "wall_clock_s": 600, "max_episodes": 3},
        "budget_derivation": {**DEFAULTS, "seconds_per_action": 0},
    }

    with pytest.raises(ValueError, match="seconds_per_action"):
        derive_sample_budget(mid, config)


def test_sample_overlay_budget_passes_strict_app_config_validation(tmp_path):
    short, mid, long = _samples()
    config = load_config()
    base = eval_overlay(config)

    for sample in (mid, long):
        overlay = {
            **base,
            **sample_overlay(
                run_id="budget-test",
                branch="main",
                work=tmp_path / sample.sample_id,
                sample=sample,
                config=config,
            ),
        }
        path, _ = write_overlay(tmp_path / f"{sample.sample_id}.json", overlay)
        app = load_app_config(path).config
        assert app.budget.max_total_actions == sample.max_steps
        assert "effective_budget" not in overlay

    short_budget = sample_overlay(
        run_id="short-test",
        branch="main",
        work=tmp_path / "short",
        sample=short,
        config=config,
    )["budget"]
    mid_budget = sample_overlay(
        run_id="mid-test",
        branch="main",
        work=tmp_path / "mid",
        sample=mid,
        config=config,
    )["budget"]
    assert short_budget != mid_budget


def test_load_config_supplies_defaults_when_derivation_section_is_absent(tmp_path, monkeypatch):
    from evals import runconfig

    content = json.loads(runconfig.CONFIG_PATH.read_text(encoding="utf-8"))
    content.pop("budget_derivation", None)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    monkeypatch.setattr(runconfig, "CONFIG_PATH", path)

    assert load_config()["budget_derivation"] == BUDGET_DERIVATION_DEFAULTS


def test_run_record_contains_effective_budget(tmp_path):
    budget = {"max_total_actions": 250, "wall_clock_s": 10120, "timeout": 10420, "max_episodes": 3}

    _record(tmp_path, "eval-sample", budget=budget)

    record = RunOneRecord.model_validate_json((tmp_path / "run.json").read_text("utf-8"))
    payload = json.loads((tmp_path / "run.json").read_text("utf-8"))
    assert payload["effective_budget"] == budget
    assert record.run_id == "eval-sample"


def test_sample_timeout_is_derived_for_each_tier():
    short, mid, long = _samples()
    config = {
        "timeout": 600,
        "budget": {"max_total_actions": 60, "wall_clock_s": 600, "max_episodes": 3},
    }

    assert sample_timeout(short, config) == 600
    assert sample_timeout(mid, config) == 10420
    assert sample_timeout(long, config) == 29220


def test_solver_uses_sample_timeout_for_worker_process(tmp_path, monkeypatch):
    _, mid, _ = _samples()
    captured = []

    @contextmanager
    def fake_services(**_options):
        yield {}

    monkeypatch.setattr(
        "evals.agent_short_goal_run.solver.solver.load_samples", lambda _version: [mid]
    )
    monkeypatch.setattr("evals.agent_short_goal_run.solver.solver.eval_services", fake_services)
    monkeypatch.setattr(
        "evals.agent_short_goal_run.solver.solver.subprocess.run",
        lambda *args, **kwargs: captured.append(kwargs["timeout"]),
    )
    state = TaskState(
        model="none",
        sample_id=mid.sample_id,
        epoch=1,
        input="run",
        messages=[],
        metadata={"sample_id": mid.sample_id},
    )
    config = {
        "timeout": 600,
        "budget": {"max_total_actions": 60, "wall_clock_s": 600, "max_episodes": 3},
    }
    solve = run_one_solver(
        report_dir=str(tmp_path),
        run_config_path=str(tmp_path / "run_config.json"),
        models={},
        timeout=600,
        version="v20261028_mid",
        transcript=False,
        budget_config=config,
    )

    asyncio.run(solve(state, None))

    assert captured == [10420]


def test_baseline_context_records_derivation_and_sample_budgets(tmp_path, monkeypatch):
    monkeypatch.setattr("evals.agent_short_goal_run.task.load_env_file", lambda: None)

    agent_short_goal_run(
        version="v20261028_mid",
        samples=["mid_heal_buy_return"],
        log_dir=str(tmp_path),
        grader_model=None,
        transcript=False,
    )

    context = json.loads((tmp_path / "baseline_context.json").read_text(encoding="utf-8"))
    assert context["budget_derivation"] == {
        "seconds_per_action": 40,
        "reserve_s": 120,
        "timeout_margin_s": 300,
        "long_max_episodes": 6,
    }
    assert context["sample_budgets"]["mid_heal_buy_return"] == {
        "max_total_actions": 250,
        "wall_clock_s": 10120,
        "timeout": 10420,
        "max_episodes": 3,
    }
