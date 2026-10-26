"""Official OpenAI grading uses native reasoning options without vendor-only fields."""

import pytest
from inspect_ai.model import GenerateConfig

from evals.common.grader_model import build_grader_model
from evals.runconfig import ResultGraderConfig


@pytest.mark.parametrize(("thinking", "effort"), [(False, "none"), (True, "medium")])
def test_openai_grader_builds_native_options_without_calling_a_model(
    monkeypatch: pytest.MonkeyPatch, thinking: bool, effort: str
) -> None:
    captured: dict[str, object] = {}
    sentinel = object()

    def fake_model(model: str, **kwargs: object) -> object:
        captured.update(model=model, **kwargs)
        return sentinel

    monkeypatch.setenv("EVAL_TEST_OPENAI_KEY", "placeholder")
    monkeypatch.setattr("evals.common.grader_model.get_model", fake_model)
    grader = ResultGraderConfig(
        model="openai/gpt-6-luna",
        base_url="https://api.openai.com/v1",
        api_key_env="EVAL_TEST_OPENAI_KEY",
        temperature=0.0,
        max_tokens=8192,
        timeout_s=180,
        thinking=thinking,
    )

    result = build_grader_model(grader)

    assert result is sentinel
    assert captured["model"] == "openai/gpt-6-luna"
    assert captured["base_url"] == "https://api.openai.com/v1"
    config = captured["config"]
    assert isinstance(config, GenerateConfig)
    assert config.reasoning_effort == effort
    assert config.extra_body == {}
    assert (config.max_tokens, config.timeout) == (8192, 180)
