"""`build_vision_provider`：给 world 造视觉 provider 的接线工厂。

缺省造 Qwen 视觉 provider（型号 qwen3.8-max、温度 0、超时 20），按型号名前缀选厂商，
json_mode 显式传值生效，不认识的前缀抛 ValueError。配置经 `config()` 读，超时经
手写假 `urlopen` 观察。
"""

from __future__ import annotations

import json

import pytest

from pokemon_agent.brain.schemas import LlmCompleteReq
from pokemon_agent.brain.vision_factory import build_vision_provider


class _FakeResponse:
    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        reply = {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}], "usage": {}}
        return json.dumps(reply).encode()


@pytest.fixture(autouse=True)
def _set_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setenv("ARK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")


@pytest.fixture
def captured_timeouts(monkeypatch: pytest.MonkeyPatch) -> list[float | None]:
    timeouts: list[float | None] = []

    def fake_urlopen(req: object, timeout: float | None = None) -> _FakeResponse:
        timeouts.append(timeout)
        return _FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return timeouts


def test_build_vision_provider_defaults_to_a_qwen_provider(
    captured_timeouts: list[float | None],
) -> None:
    provider = build_vision_provider()

    assert provider.config()["provider"] == "QwenProvider"
    assert provider.config()["model"] == "qwen3.8-max"
    assert provider.config()["temperature"] == "0.0"

    provider.complete(LlmCompleteReq(prompt="hi"))

    assert captured_timeouts == [20]


@pytest.mark.parametrize(
    ("model", "provider_name"),
    [("doubao-x", "ArkProvider"), ("deepseek-x", "DeepSeekProvider")],
)
def test_build_vision_provider_picks_the_vendor_by_prefix(model: str, provider_name: str) -> None:
    provider = build_vision_provider(model)

    assert provider.config()["provider"] == provider_name


@pytest.mark.parametrize(("json_mode", "expected"), [(True, "true"), (False, "false")])
def test_build_vision_provider_honours_an_explicit_json_mode(
    json_mode: bool, expected: str
) -> None:
    provider = build_vision_provider("qwen-a", json_mode=json_mode)

    assert provider.config()["json_mode"] == expected


def test_build_vision_provider_rejects_an_unknown_prefix() -> None:
    with pytest.raises(ValueError):
        build_vision_provider("llama")
