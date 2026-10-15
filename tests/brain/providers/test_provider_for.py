"""``provider_for`` 选型契约：前缀选厂商、未知前缀报错、参数转发与新实例。"""

from __future__ import annotations

import pytest
from _doubles.http import FakeUrlopen

from pokemon_agent.brain.providers import (
    ArkProvider,
    DeepSeekProvider,
    QwenProvider,
    provider_for,
)
from pokemon_agent.brain.schemas import LlmCompleteReq

KEY_VARS = ("DASHSCOPE_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ARK_API_KEY", "DEEPSEEK_API_KEY")


@pytest.fixture(autouse=True)
def _no_keys_in_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """每个测试先把四个 key 变量全清掉，不依赖机器上的真实环境。"""

    for name in KEY_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def fake_urlopen(monkeypatch: pytest.MonkeyPatch) -> FakeUrlopen:
    """把共享替身装到 ``urllib.request.urlopen`` 上。"""

    fake = FakeUrlopen()
    monkeypatch.setattr("urllib.request.urlopen", fake)
    return fake


@pytest.mark.parametrize(
    ("model", "expected_cls"),
    [
        ("qwen3.8-max", QwenProvider),
        ("doubao-seed", ArkProvider),
        ("deepseek-flash", DeepSeekProvider),
        ("Qwen-x", QwenProvider),
        ("qwen", QwenProvider),
        ("doubao-qwen", ArkProvider),
    ],
)
def test_the_model_prefix_picks_the_vendor_case_insensitively_and_only_from_the_start(
    model: str, expected_cls: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    """前缀选厂商：三家各自认领；大小写不敏感；只看开头（doubao-qwen 是 Ark）。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "k")
    monkeypatch.setenv("ARK_API_KEY", "k")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")

    provider = provider_for(model, temperature=0.3)

    assert isinstance(provider, expected_cls)


@pytest.mark.parametrize("model", ["xqwen", "gpt-4"])
def test_an_unknown_prefix_raises_value_error_naming_the_model(
    model: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """不认识的前缀抛 ValueError，消息里带该型号名与候选前缀表。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "k")

    with pytest.raises(ValueError, match=model):
        provider_for(model, temperature=0.3)


def test_an_empty_model_name_and_a_missing_temperature_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空型号名抛 AssertionError；不给温度抛 TypeError。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "k")

    with pytest.raises(AssertionError, match="empty model name"):
        provider_for("", temperature=0.3)

    with pytest.raises(TypeError):
        provider_for("qwen3.8-max")


@pytest.mark.parametrize("vendor_model", ["qwen3.8-max", "doubao-seed", "deepseek-flash"])
def test_max_tokens_defaults_to_25600_and_an_explicit_value_lands_verbatim(
    vendor_model: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """max_tokens 不给时用各家缺省 '25600'，给了就原样落到 config()。"""

    for env in ("DASHSCOPE_API_KEY", "ARK_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.setenv(env, "k")

    default = provider_for(vendor_model, temperature=0.3)
    explicit = provider_for(vendor_model, temperature=0.3, max_tokens=5)

    assert default.config()["max_tokens"] == "25600"
    assert explicit.config()["max_tokens"] == "5"


def test_extra_kwargs_are_forwarded_and_each_call_builds_a_fresh_instance(
    monkeypatch: pytest.MonkeyPatch, fake_urlopen: FakeUrlopen
) -> None:
    """timeout/json_mode/thinking 原样转发；连调两次同样参数得到两个不同实例。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")

    first = provider_for("qwen3.8-max", temperature=0.3, timeout=9, json_mode=True, thinking=True)
    second = provider_for("qwen3.8-max", temperature=0.3, timeout=9, json_mode=True, thinking=True)

    assert first is not second

    first.complete(LlmCompleteReq(prompt="hi"))
    body = fake_urlopen.calls[0]["json"]

    assert fake_urlopen.calls[0]["timeout"] == 9
    assert body["response_format"] == {"type": "json_object"}
    assert body["enable_thinking"] is True
