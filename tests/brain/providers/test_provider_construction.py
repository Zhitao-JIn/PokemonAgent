"""provider 构造期契约：温度、型号名、key 查找顺序、缺省值与 ``config()`` 自报家底。"""

from __future__ import annotations

from typing import Any

import pytest
from _doubles.http import FakeUrlopen

from pokemon_agent.brain.providers import (
    ArkProvider,
    DeepSeekProvider,
    QwenProvider,
)
from pokemon_agent.brain.schemas import LlmCompleteReq

KEY_VARS = ("DASHSCOPE_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ARK_API_KEY", "DEEPSEEK_API_KEY")

VENDOR_ENV = {
    "qwen": "DASHSCOPE_API_KEY",
    "ark": "ARK_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}


def make(vendor: str, **kwargs: Any) -> Any:
    """三家构造统一入口：Ark 的 model 是位置必填，其余有缺省。"""

    if vendor == "qwen":
        return QwenProvider(**kwargs)
    if vendor == "ark":
        return ArkProvider(kwargs.pop("model", "m"), **kwargs)
    return DeepSeekProvider(**kwargs)


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
    ("vendor", "temperature", "accepted"),
    [
        ("qwen", 0, True),
        ("qwen", 2.0, True),
        ("qwen", -0.1, False),
        ("qwen", 2.1, False),
        ("ark", 0, True),
        ("ark", 2.0, True),
        ("ark", -0.1, False),
        ("ark", 2.1, False),
        ("deepseek", 0, True),
        ("deepseek", 2.0, True),
        ("deepseek", -0.1, False),
        ("deepseek", 2.1, False),
    ],
)
def test_the_temperature_must_sit_in_the_closed_interval_from_zero_to_two(
    vendor: str,
    temperature: float,
    accepted: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """温度必须在 [0, 2] 闭区间内：0 与 2.0 收下，-0.1 与 2.1 拒绝（assert）。"""

    monkeypatch.setenv(VENDOR_ENV[vendor], "k")

    if accepted:
        provider = make(vendor, temperature=temperature)

        assert provider.config()["temperature"] == str(temperature)
    else:
        with pytest.raises(ValueError, match="temperature out of range"):
            make(vendor, temperature=temperature)


@pytest.mark.parametrize("vendor", ["qwen", "deepseek"])
def test_the_temperature_is_a_required_keyword_for_qwen_and_deepseek(
    vendor: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Qwen 与 DeepSeek 不给 temperature 直接 TypeError——温度必须显式写出来。"""

    monkeypatch.setenv(VENDOR_ENV[vendor], "k")

    with pytest.raises(TypeError):
        make(vendor)


def test_the_temperature_is_a_required_keyword_for_ark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ark 给了 model 但不给 temperature 也是 TypeError。"""

    monkeypatch.setenv("ARK_API_KEY", "k")

    with pytest.raises(TypeError):
        ArkProvider("m")


@pytest.mark.parametrize("vendor", ["qwen", "deepseek", "ark"])
def test_an_empty_model_name_is_rejected_at_construction(
    vendor: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """型号名为空串在构造时就被拒（三家消息不同，配置值用 ValueError）。"""

    monkeypatch.setenv(VENDOR_ENV[vendor], "k")

    with pytest.raises(ValueError):
        make(vendor, model="", temperature=0.0)


def test_ark_requires_a_model_while_the_other_two_have_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ark 的型号名必填（pro/turbo 二选一，不设默认）；Qwen 与 DeepSeek 各有缺省。"""

    monkeypatch.setenv("ARK_API_KEY", "k")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "k")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")

    with pytest.raises(TypeError):
        ArkProvider(temperature=0.0)

    qwen = QwenProvider(temperature=0.0)
    deepseek = DeepSeekProvider(temperature=0.0)

    assert qwen.config()["model"] == "qwen3.8-max"
    assert deepseek.config()["model"] == "deepseek-flash"


def test_a_missing_key_fails_at_construction_naming_every_candidate_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没有 key 时构造就失败（不是调用时），消息点名所有候选变量。"""

    with pytest.raises(RuntimeError, match="DASHSCOPE_API_KEY / ANTHROPIC_AUTH_TOKEN 均未设置"):
        QwenProvider(temperature=0.0)

    with pytest.raises(RuntimeError, match="ARK_API_KEY 均未设置"):
        ArkProvider("m", temperature=0.0)

    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY 均未设置"):
        DeepSeekProvider(temperature=0.0)


def test_qwen_prefers_the_primary_key_variable(
    monkeypatch: pytest.MonkeyPatch, fake_urlopen: FakeUrlopen
) -> None:
    """Qwen 的 key 查找顺序：两个变量都设时 DASHSCOPE_API_KEY 优先。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-primary")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-fallback")
    provider = QwenProvider(temperature=0.0)
    provider.complete(LlmCompleteReq(prompt="hi"))

    assert fake_urlopen.calls[0]["headers"]["authorization"] == "Bearer sk-primary"


def test_qwen_falls_through_an_empty_key_variable_to_the_anthropic_token(
    monkeypatch: pytest.MonkeyPatch, fake_urlopen: FakeUrlopen
) -> None:
    """DASHSCOPE_API_KEY 是空串时被跳过，落到 ANTHROPIC_AUTH_TOKEN。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-fallback")
    provider = QwenProvider(temperature=0.0)
    provider.complete(LlmCompleteReq(prompt="hi"))

    assert fake_urlopen.calls[0]["headers"]["authorization"] == "Bearer sk-fallback"


def test_ark_and_deepseek_read_only_their_own_variable(
    monkeypatch: pytest.MonkeyPatch, fake_urlopen: FakeUrlopen
) -> None:
    """Ark 只认 ARK_API_KEY、DeepSeek 只认 DEEPSEEK_API_KEY，别家的变量不影响。"""

    monkeypatch.setenv("ARK_API_KEY", "sk-ark")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
    ark = ArkProvider("m", temperature=0.0)
    deepseek = DeepSeekProvider(temperature=0.0)
    ark.complete(LlmCompleteReq(prompt="hi"))
    deepseek.complete(LlmCompleteReq(prompt="hi"))

    assert fake_urlopen.calls[0]["headers"]["authorization"] == "Bearer sk-ark"
    assert fake_urlopen.calls[1]["headers"]["authorization"] == "Bearer sk-ds"


def test_defaults_and_base_urls_are_paired_per_vendor(monkeypatch: pytest.MonkeyPatch) -> None:
    """max_tokens 缺省 '25600'、multimodal 为真；三家的 base_url 各自配套。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "k")
    monkeypatch.setenv("ARK_API_KEY", "k")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")

    qwen = QwenProvider(temperature=0.0)
    ark = ArkProvider("m", temperature=0.0)
    deepseek = DeepSeekProvider(temperature=0.0)

    for provider in (qwen, ark, deepseek):
        assert provider.config()["max_tokens"] == "25600"
        assert provider.multimodal is True

    assert qwen.config()["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert ark.config()["base_url"] == "https://ark.cn-beijing.volces.com/api/v3"
    assert deepseek.config()["base_url"] == "https://api.deepseek.com"


def test_config_reports_seven_string_keys_and_never_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """config() 恰好七个键、值全是字符串，且把独特的 key 值藏住不报。"""

    secret = "sk-very-unique-secret-value-42"
    monkeypatch.setenv("DASHSCOPE_API_KEY", secret)
    provider = QwenProvider(temperature=0.3, max_tokens=77, json_mode=True, thinking=True)
    config = provider.config()

    assert set(config) == {
        "provider",
        "model",
        "temperature",
        "max_tokens",
        "json_mode",
        "thinking",
        "base_url",
    }
    assert all(isinstance(value, str) for value in config.values())

    assert secret not in str(config)
