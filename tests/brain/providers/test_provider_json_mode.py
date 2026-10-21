"""三个厂商 Provider 的 `json_mode` 开关：默认不带 `response_format`，打开后请求体带
`{"type": "json_object"}`。

这里不连网：把 `urllib.request.urlopen` 换成一个记下请求体的假实现，
只看**真正发出去的 JSON**长什么样——开关是不是落到了线上，比"构造函数收了参数"重要。
"""

from __future__ import annotations

import json

import pytest

from pokemon_agent.brain.providers import (
    ArkProvider,
    DeepSeekProvider,
    QwenProvider,
    provider_for,
)
from pokemon_agent.brain.schemas import LlmCompleteReq

_PROVIDERS = [
    (QwenProvider, "DASHSCOPE_API_KEY", "qwen3.8-max"),
    (ArkProvider, "ARK_API_KEY", "doubao-seed-2-1-pro-260628"),
    (DeepSeekProvider, "DEEPSEEK_API_KEY", "deepseek-flash"),
]


class _FakeResponse:
    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        reply = {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}], "usage": {}}
        return json.dumps(reply).encode()


@pytest.fixture
def sent_bodies(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    bodies: list[dict] = []

    def fake_urlopen(req: object, timeout: float | None = None) -> _FakeResponse:
        bodies.append(json.loads(req.data))  # type: ignore[attr-defined]
        return _FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    for _cls, key_env, _model in _PROVIDERS:
        monkeypatch.setenv(key_env, "test-key")
    return bodies


@pytest.mark.parametrize(("provider_cls", "_key_env", "model"), _PROVIDERS)
def test_provider_sends_no_response_format_by_default(
    sent_bodies: list[dict], provider_cls: type, _key_env: str, model: str
) -> None:
    # Arrange
    provider = provider_cls(model, temperature=0.0)

    # Act
    provider.complete(LlmCompleteReq(prompt='只输出 json：{"ok": true}'))

    # Assert
    assert "response_format" not in sent_bodies[0]


@pytest.mark.parametrize(("provider_cls", "_key_env", "model"), _PROVIDERS)
def test_provider_sends_json_object_when_json_mode_is_on(
    sent_bodies: list[dict], provider_cls: type, _key_env: str, model: str
) -> None:
    # Arrange
    provider = provider_cls(model, temperature=0.0, json_mode=True)

    # Act
    provider.complete(LlmCompleteReq(prompt='只输出 json：{"ok": true}'))

    # Assert
    assert sent_bodies[0]["response_format"] == {"type": "json_object"}
    assert provider.config()["json_mode"] == "true"


def test_provider_for_forwards_json_mode(sent_bodies: list[dict]) -> None:
    # Arrange
    provider = provider_for("deepseek-flash", temperature=0.0, json_mode=True)

    # Act
    provider.complete(LlmCompleteReq(prompt='只输出 json：{"ok": true}'))

    # Assert
    assert sent_bodies[0]["response_format"] == {"type": "json_object"}


def test_build_llm_providers_hands_json_mode_to_every_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    from pokemon_agent.brain import BrainLlmConfig, LinkSpec, build_llm_providers

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    spec = LinkSpec(model="deepseek-flash", temperature=0.0, max_tokens=100, timeout_s=45)
    config = BrainLlmConfig(text=spec, judge=spec, verify=spec, plan=spec, json_mode=True)

    # Act
    providers = build_llm_providers(config)

    # Assert
    assert [p.config()["json_mode"] for p in providers if p is not None] == ["true"] * 4


_THINKING_BODIES = {
    QwenProvider: ("enable_thinking", True, False),
    ArkProvider: ("thinking", {"type": "enabled"}, {"type": "disabled"}),
    DeepSeekProvider: ("thinking", {"type": "enabled"}, {"type": "disabled"}),
}


@pytest.mark.parametrize(("provider_cls", "_key_env", "model"), _PROVIDERS)
def test_provider_says_thinking_explicitly_both_ways(
    sent_bodies: list[dict], provider_cls: type, _key_env: str, model: str
) -> None:
    # Arrange
    field, on_value, off_value = _THINKING_BODIES[provider_cls]
    off = provider_cls(model, temperature=0.0)
    on = provider_cls(model, temperature=0.0, thinking=True)

    # Act
    off.complete(LlmCompleteReq(prompt="json"))
    on.complete(LlmCompleteReq(prompt="json"))

    # Assert：服务端默认是开，所以"关"也要显式发
    assert sent_bodies[0][field] == off_value
    assert sent_bodies[1][field] == on_value
    assert on.config()["thinking"] == "true"


def test_build_llm_providers_turns_thinking_on_for_plan_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    from pokemon_agent.brain import BrainLlmConfig, LinkSpec, build_llm_providers

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    plain = LinkSpec(model="deepseek-flash", temperature=0.0, max_tokens=100, timeout_s=45)
    thinking = LinkSpec(
        model="deepseek-flash", temperature=0.0, max_tokens=100, timeout_s=420, thinking=True
    )
    config = BrainLlmConfig(text=plain, judge=plain, verify=plain, plan=thinking)

    # Act
    decide, judge, verify, plan = build_llm_providers(config)

    # Assert：只有 plan 开思考，并且它的超时被放宽
    assert [p.config()["thinking"] for p in (decide, judge, verify, plan)] == [
        "false",
        "false",
        "false",
        "true",
    ]
    assert plan._timeout > decide._timeout
