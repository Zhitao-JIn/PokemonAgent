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
from evals.runconfig import ResultGraderConfig, load_config, resolve_result_grader

GRADER_KEYS = ("model", "base_url", "api_key_env", "temperature", "max_tokens", "timeout_s")


Assembly = tuple[dict[str, Any], list[ResultGraderConfig], Callable[[str | None], Task]]


def test_checked_in_grader_configuration_is_explicit_and_distinct() -> None:
    configuration = load_config()

    grader = resolve_result_grader(configuration["evaluation_models"])

    assert grader.model_dump() == {
        "model": "openai-api/dashscope/qwen3.7-plus",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "DASHSCOPE_API_KEY",
        "temperature": 0.0,
        "max_tokens": 1024,
        "timeout_s": 120,
    }
    assert configuration["evaluation_models"]["test_text"] == "openai-api/deepseek/deepseek-flash"
    assert grader.model.rsplit("/", 1)[-1] not in configuration["models"].values()


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


@pytest.mark.parametrize("link", runconfig.MODEL_LINKS)
@pytest.mark.parametrize("prefixed", [False, True])
@pytest.mark.parametrize("origin", ["configured", "override"])
def test_task_rejects_grader_matching_any_tested_model(
    assembly: Assembly, link: str, prefixed: bool, origin: str
) -> None:
    configuration, seen, build = assembly
    name = configuration["models"][link]
    candidate = f"openai-api/vendor/{name}" if prefixed else name
    if origin == "configured":
        configuration["evaluation_models"]["result_grader"]["model"] = candidate

    with pytest.raises(ValueError, match=name):
        build(candidate if origin == "override" else None)

    assert seen == []


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
    assert evaluation_before["test_text"] == "openai-api/deepseek/deepseek-flash"
    if override is not None and override.lower() == "none":
        assert seen == [] and len(task.scorer) == 8
    else:
        assert len(seen) == 1 and len(task.scorer) == 9
        assert registry_info(task.scorer[-1]).name == "llm_task_completion_scorer"
        expected = {**evaluation_before["result_grader"]}
        if override is not None:
            expected["model"] = override
        assert seen[0].model_dump() == expected
