"""Provider identity is public, read-only and available without making a request."""

import pytest

from pokemon_agent.brain.providers import (
    ArkProvider,
    ClaudeProvider,
    DeepSeekProvider,
    OpenAIProvider,
    QwenProvider,
)


@pytest.mark.parametrize(
    ("provider_class", "name", "model"),
    [
        (QwenProvider, "qwen", "qwen3.8-flash"),
        (ArkProvider, "ark", "doubao-seed-2-0-pro-260215"),
        (DeepSeekProvider, "deepseek", "deepseek-flash"),
        (ClaudeProvider, "claude", "claude-haiku-5-5"),
        (OpenAIProvider, "openai", "gpt-test"),
    ],
)
def test_provider_exposes_its_name_and_the_original_model_without_network(
    provider_class: type[
        QwenProvider | ArkProvider | DeepSeekProvider | ClaudeProvider | OpenAIProvider
    ],
    name: str,
    model: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable in provider_class.API_KEY_ENVS:
        monkeypatch.setenv(variable, "placeholder")
    provider = provider_class(model, temperature=0.0)

    assert name == provider.PROVIDER_NAME
    assert provider.model_name == model
    with pytest.raises(AttributeError):
        provider.model_name = "changed"
