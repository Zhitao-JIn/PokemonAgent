"""Budget adapters expose real provider identity as read-only properties."""

import pytest

from pokemon_agent.brain.providers import (
    ArkProvider,
    ClaudeProvider,
    DeepSeekProvider,
    OpenAIProvider,
    QwenProvider,
)
from pokemon_agent.direct.budget_provider import BudgetProvider


@pytest.mark.parametrize(
    "provider_class", [QwenProvider, ArkProvider, DeepSeekProvider, ClaudeProvider, OpenAIProvider]
)
def test_budget_wrapping_preserves_public_readonly_identity(
    provider_class: type[
        QwenProvider | ArkProvider | DeepSeekProvider | ClaudeProvider | OpenAIProvider
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in provider_class.API_KEY_ENVS:
        monkeypatch.setenv(name, "placeholder")
    provider = provider_class("original-model", temperature=0.0)
    bounded = BudgetProvider(provider, None, 60, "test")

    assert bounded.PROVIDER_NAME == provider.PROVIDER_NAME
    assert bounded.model_name == "original-model"
    with pytest.raises(AttributeError):
        bounded.model_name = "changed"
    with pytest.raises(AttributeError):
        bounded.PROVIDER_NAME = "changed"
