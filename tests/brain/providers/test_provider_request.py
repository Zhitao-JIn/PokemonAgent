"""provider 请求形状契约：URL 与头、请求体、思考开关的覆盖规则、超时传递与空 prompt。"""

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
VENDOR_KEY = {"qwen": "sk-q", "ark": "sk-a", "deepseek": "sk-d"}
VENDOR_URL = {
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    "ark": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
    "deepseek": "https://api.deepseek.com/chat/completions",
}


def make(vendor: str, **kwargs: Any) -> Any:
    """三家构造统一入口：Ark 的 model 是位置必填，其余有缺省。"""

    if vendor == "qwen":
        return QwenProvider(**kwargs)
    if vendor == "ark":
        return ArkProvider(kwargs.pop("model", "doubao-x"), **kwargs)
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


@pytest.mark.parametrize("vendor", ["qwen", "ark", "deepseek"])
def test_the_request_lands_on_base_url_chat_completions_with_bearer_and_json_headers(
    vendor: str,
    monkeypatch: pytest.MonkeyPatch,
    fake_urlopen: FakeUrlopen,
) -> None:
    """请求落在 base_url + /chat/completions，带 Bearer 与 JSON 头（三家参数化）。"""

    monkeypatch.setenv(VENDOR_ENV[vendor], VENDOR_KEY[vendor])
    provider = make(vendor, temperature=0.3)

    provider.complete(LlmCompleteReq(prompt="hi"))

    assert fake_urlopen.call_count == 1
    call = fake_urlopen.calls[0]

    assert call["url"] == VENDOR_URL[vendor]
    assert call["headers"]["authorization"] == f"Bearer {VENDOR_KEY[vendor]}"
    assert call["headers"]["content-type"] == "application/json"


@pytest.mark.parametrize("vendor", ["qwen", "ark", "deepseek"])
def test_the_body_carries_model_numeric_temperature_max_tokens_and_one_user_message(
    vendor: str,
    monkeypatch: pytest.MonkeyPatch,
    fake_urlopen: FakeUrlopen,
) -> None:
    """请求体含型号、数字温度、数字 max_tokens 与单条 user 消息（三家参数化）。"""

    monkeypatch.setenv(VENDOR_ENV[vendor], VENDOR_KEY[vendor])
    provider = make(vendor, temperature=0.3, max_tokens=77)

    provider.complete(LlmCompleteReq(prompt="hi"))
    body = fake_urlopen.calls[0]["json"]

    assert body["model"] == provider.config()["model"]
    assert body["temperature"] == 0.3
    assert body["max_tokens"] == 77
    assert body["messages"] == [{"role": "user", "content": "hi"}]


def test_thinking_defaults_to_off_with_vendor_specific_shapes(
    monkeypatch: pytest.MonkeyPatch, fake_urlopen: FakeUrlopen
) -> None:
    """默认关：Qwen 是扁平布尔 ``enable_thinking: false``，Ark 与 DeepSeek 是嵌套禁用对象。"""

    for env in VENDOR_ENV.values():
        monkeypatch.setenv(env, "sk-x")
    qwen = QwenProvider(temperature=0.3)
    ark = ArkProvider("doubao-x", temperature=0.3)
    deepseek = DeepSeekProvider(temperature=0.3)

    qwen.complete(LlmCompleteReq(prompt="hi"))
    ark.complete(LlmCompleteReq(prompt="hi"))
    deepseek.complete(LlmCompleteReq(prompt="hi"))

    qwen_body = fake_urlopen.calls[0]["json"]
    ark_body = fake_urlopen.calls[1]["json"]
    deepseek_body = fake_urlopen.calls[2]["json"]

    assert qwen_body["enable_thinking"] is False
    assert ark_body["thinking"] == {"type": "disabled"}
    assert deepseek_body["thinking"] == {"type": "disabled"}


def test_thinking_on_uses_the_enabled_shape_per_vendor(
    monkeypatch: pytest.MonkeyPatch, fake_urlopen: FakeUrlopen
) -> None:
    """构造时开：Qwen 扁平真，Ark 与 DeepSeek 嵌套 enabled。"""

    for env in VENDOR_ENV.values():
        monkeypatch.setenv(env, "sk-x")
    qwen = QwenProvider(temperature=0.3, thinking=True)
    ark = ArkProvider("doubao-x", temperature=0.3, thinking=True)
    deepseek = DeepSeekProvider(temperature=0.3, thinking=True)

    qwen.complete(LlmCompleteReq(prompt="hi"))
    ark.complete(LlmCompleteReq(prompt="hi"))
    deepseek.complete(LlmCompleteReq(prompt="hi"))

    assert fake_urlopen.calls[0]["json"]["enable_thinking"] is True
    assert fake_urlopen.calls[1]["json"]["thinking"] == {"type": "enabled"}
    assert fake_urlopen.calls[2]["json"]["thinking"] == {"type": "enabled"}


def test_req_thinking_overrides_the_constructor_once_and_none_falls_back(
    monkeypatch: pytest.MonkeyPatch, fake_urlopen: FakeUrlopen
) -> None:
    """构造时开：req.thinking=False 关、True 开、None 沿用构造时的开。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    provider = QwenProvider(temperature=0.3, thinking=True)

    provider.complete(LlmCompleteReq(prompt="hi", thinking=False))
    provider.complete(LlmCompleteReq(prompt="hi", thinking=True))
    provider.complete(LlmCompleteReq(prompt="hi", thinking=None))

    assert fake_urlopen.calls[0]["json"]["enable_thinking"] is False
    assert fake_urlopen.calls[1]["json"]["enable_thinking"] is True
    assert fake_urlopen.calls[2]["json"]["enable_thinking"] is True


def test_req_thinking_true_turns_on_a_default_off_provider(
    monkeypatch: pytest.MonkeyPatch, fake_urlopen: FakeUrlopen
) -> None:
    """构造时缺省（关）：req.thinking=True 开、None 沿用关。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    provider = QwenProvider(temperature=0.3)

    provider.complete(LlmCompleteReq(prompt="hi", thinking=True))
    provider.complete(LlmCompleteReq(prompt="hi", thinking=None))

    assert fake_urlopen.calls[0]["json"]["enable_thinking"] is True
    assert fake_urlopen.calls[1]["json"]["enable_thinking"] is False


@pytest.mark.parametrize("timeout", [45, 9])
def test_the_construction_timeout_reaches_urlopen_verbatim(
    timeout: int, monkeypatch: pytest.MonkeyPatch, fake_urlopen: FakeUrlopen
) -> None:
    """构造时的 timeout 原样传给 urlopen：缺省 45，给了就用给的。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    provider = QwenProvider(temperature=0.3, timeout=timeout)

    provider.complete(LlmCompleteReq(prompt="hi"))

    assert fake_urlopen.calls[0]["timeout"] == timeout


def test_a_per_call_timeout_s_overrides_this_call_only(
    monkeypatch: pytest.MonkeyPatch, fake_urlopen: FakeUrlopen
) -> None:
    """``complete(req, timeout_s=x)`` 只覆盖这一次，下一次不带又回到构造时的值。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    provider = QwenProvider(temperature=0.3, timeout=9)

    provider.complete(LlmCompleteReq(prompt="hi"), timeout_s=7.5)
    provider.complete(LlmCompleteReq(prompt="hi"))

    assert fake_urlopen.calls[0]["timeout"] == 7.5
    assert fake_urlopen.calls[1]["timeout"] == 9


@pytest.mark.parametrize("bad_timeout_s", [0, -1])
def test_a_non_positive_timeout_s_is_rejected_before_any_request(
    bad_timeout_s: float, monkeypatch: pytest.MonkeyPatch, fake_urlopen: FakeUrlopen
) -> None:
    """timeout_s 为 0 或负数 → ValueError，且请求根本没发出去。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    provider = QwenProvider(temperature=0.3)

    with pytest.raises(ValueError, match="timeout_s must be positive"):
        provider.complete(LlmCompleteReq(prompt="hi"), timeout_s=bad_timeout_s)

    assert fake_urlopen.call_count == 0


def test_an_empty_prompt_is_rejected_before_any_request(
    monkeypatch: pytest.MonkeyPatch, fake_urlopen: FakeUrlopen
) -> None:
    """空 prompt 在发出请求之前就被 assert 拒掉，替身一次都没被调。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    provider = QwenProvider(temperature=0.3)

    with pytest.raises(AssertionError, match="empty prompt"):
        provider.complete(LlmCompleteReq(prompt=""))

    assert fake_urlopen.call_count == 0
