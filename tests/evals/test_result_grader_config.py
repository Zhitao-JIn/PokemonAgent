"""评分员配置与 task 装配示范：不调用模型、不读密钥、不启动服务。"""

import copy
import importlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from inspect_ai import Task
from inspect_ai._util.registry import registry_info
from inspect_ai.scorer import Scorer

from evals import runconfig
from evals.runconfig import (
    ResultGraderConfig,
    load_config,
    resolve_grader,
    resolve_result_grader,
)

GRADER_KEYS = (
    "model",
    "base_url",
    "api_key_env",
    "temperature",
    "max_tokens",
    "timeout_s",
    "thinking",
)


Assembly = tuple[dict[str, Any], list[ResultGraderConfig], Callable[[str | None], Task]]


def test_checked_in_grader_configuration_is_explicit_and_distinct() -> None:
    configuration = load_config()

    grader = resolve_result_grader(configuration["evaluation_models"])

    assert grader.model_dump() == {
        "model": "openai/gpt-6-luna",
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "temperature": 0.0,
        "max_tokens": 8192,
        "timeout_s": 180,
        "thinking": False,
    }
    assert "test_text" not in configuration["evaluation_models"]


def test_loading_config_requires_evaluation_models(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configuration = load_config()
    del configuration["evaluation_models"]
    path = tmp_path / "config.json"
    path.write_text(json.dumps(configuration), encoding="utf-8")
    monkeypatch.setattr(runconfig, "CONFIG_PATH", path)

    with pytest.raises(ValueError, match="evaluation_models"):
        load_config()


@pytest.mark.parametrize(
    "missing", [["result_grader"], *[[key] for key in GRADER_KEYS], ["model", "base_url"]]
)
def test_result_grader_configuration_lists_every_missing_key(missing: list[str]) -> None:
    evaluation = copy.deepcopy(load_config()["evaluation_models"])
    for key in missing:
        if key == "result_grader":
            del evaluation[key]
        else:
            del evaluation["result_grader"][key]

    with pytest.raises(ValueError) as caught:
        resolve_result_grader(evaluation)

    assert all(key in str(caught.value) for key in missing)


def test_resolve_grader_uses_configuration_without_an_override() -> None:
    configuration = load_config()

    grader = resolve_grader(configuration["evaluation_models"])

    assert grader == resolve_result_grader(configuration["evaluation_models"])


@pytest.mark.parametrize("disabled", ["none", "NoNe"])
def test_resolve_grader_disables_scoring_without_reading_a_model(disabled: str) -> None:
    configuration = load_config()

    assert resolve_grader(configuration["evaluation_models"], disabled) is None


def test_resolve_grader_override_changes_only_the_model() -> None:
    configuration = load_config()
    configured = resolve_result_grader(configuration["evaluation_models"])

    grader = resolve_grader(configuration["evaluation_models"], "openai-api/vendor/other")

    assert grader is not None
    assert grader.model_dump() == {**configured.model_dump(), "model": "openai-api/vendor/other"}


def test_resolve_grader_allows_the_same_model_as_a_tested_link() -> None:
    configuration = load_config()
    tested = configuration["models"]["plan_model"]
    evaluation = copy.deepcopy(configuration["evaluation_models"])
    evaluation["result_grader"]["model"] = tested

    grader = resolve_grader(evaluation)

    assert grader is not None and grader.model == tested


def test_resolve_grader_still_requires_result_grader() -> None:
    with pytest.raises(ValueError, match="result_grader"):
        resolve_grader({})


@pytest.mark.parametrize(
    ("module_name", "task_name", "solver_name", "model_key"),
    [
        ("evals.brain_choose.task", "brain_choose", "choose_solver", "text_model"),
        ("evals.brain_decompose.task", "brain_decompose", "decompose_solver", "plan_model"),
        ("evals.brain_plan.task", "brain_plan", "plan_solver", "plan_model"),
        ("evals.brain_summary.task", "brain_summary", "summary_solver", "summary_model"),
    ],
)
def test_brain_tasks_assemble_without_a_test_text_key(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    task_name: str,
    solver_name: str,
    model_key: str,
) -> None:
    module = importlib.import_module(module_name)
    configuration = copy.deepcopy(load_config())
    assert "test_text" not in configuration["evaluation_models"]
    monkeypatch.setattr(module, "load_config", lambda: copy.deepcopy(configuration))
    monkeypatch.setattr(module, "load_env_file", lambda: None)
    monkeypatch.setattr(module, solver_name, lambda model: [])

    task = getattr(module, task_name)()

    assert (
        task.metadata["grader_model"]
        == configuration["evaluation_models"]["result_grader"]["model"]
    )
    assert task.metadata["tested_model"] == configuration["models"][model_key]


def test_build_grader_model_reports_only_the_missing_environment_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from evals.common.grader_model import build_grader_model

    monkeypatch.delenv("EVAL_TEST_GRADER_KEY", raising=False)
    grader = ResultGraderConfig(
        model="fake",
        base_url="https://grader.invalid/v1",
        api_key_env="EVAL_TEST_GRADER_KEY",
        temperature=0.0,
        max_tokens=1024,
        timeout_s=120,
        thinking=True,
    )

    with pytest.raises(ValueError, match="EVAL_TEST_GRADER_KEY") as caught:
        build_grader_model(grader)

    assert "fake-value" not in str(caught.value)


@pytest.mark.parametrize(("thinking", "expected"), [(True, "enabled"), (False, "disabled")])
def test_build_grader_model_reproduces_deepseek_thinking_payload(
    monkeypatch: pytest.MonkeyPatch, thinking: bool, expected: str
) -> None:
    from evals.common.grader_model import build_grader_model

    captured: dict[str, Any] = {}

    def fake_model(model: str, **options: object) -> object:
        captured.update(options)
        return object()

    monkeypatch.setenv("EVAL_TEST_GRADER_KEY", "fake-key")
    monkeypatch.setattr("evals.common.grader_model.get_model", fake_model)
    grader = ResultGraderConfig(
        model="openai-api/deepseek/deepseek-flash",
        base_url="https://api.deepseek.com",
        api_key_env="EVAL_TEST_GRADER_KEY",
        temperature=0.0,
        max_tokens=8192,
        timeout_s=180,
        thinking=thinking,
    )

    build_grader_model(grader)

    generation = captured["config"]
    assert generation.extra_body == {"thinking": {"type": expected}}
    assert generation.temperature == 0.0
    assert (generation.max_tokens, generation.timeout) == (8192, 180)


@pytest.fixture
def assembly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Assembly:
    """只组装 task；真实 scorer 工厂惰性构造，不触发模型调用。"""
    module = importlib.import_module("evals.agent_short_goal_run.task")
    configuration = copy.deepcopy(load_config())
    configuration["models"] = {key: f"tested-{key}" for key in runconfig.MODEL_LINKS}
    seen: list[ResultGraderConfig] = []
    real_factory = module.llm_task_completion_scorer

    def capture(backend: str, grader: ResultGraderConfig) -> Scorer:
        seen.append(grader)
        return real_factory(backend, grader)

    monkeypatch.setattr(module, "load_config", lambda: copy.deepcopy(configuration))
    monkeypatch.setattr(module, "load_env_file", lambda: None)
    monkeypatch.setattr(module, "llm_task_completion_scorer", capture)

    def build(override: str | None) -> Task:
        return module.agent_short_goal_run(
            samples=["knowledge_door_transition"],
            log_dir=str(tmp_path),
            transcript=False,
            **({"grader_model": override} if override is not None else {}),
        )

    return configuration, seen, build


@pytest.mark.parametrize(
    "override", [None, "none", "NoNe", "openai-api/vendor/other-grader", "other-grader"]
)
def test_task_defaults_disables_or_overrides_only_the_grader_model(
    assembly: Assembly, override: str | None
) -> None:
    configuration, seen, build = assembly
    evaluation_before = copy.deepcopy(configuration["evaluation_models"])

    task = build(override)

    assert configuration["evaluation_models"] == evaluation_before
    if override is not None and override.lower() == "none":
        assert seen == [] and len(task.scorer) == 8
    else:
        assert len(seen) == 1 and len(task.scorer) == 9
        assert registry_info(task.scorer[-1]).name == "llm_task_completion_scorer"
        expected = {**evaluation_before["result_grader"]}
        if override is not None:
            expected["model"] = override
        assert seen[0].model_dump() == expected
