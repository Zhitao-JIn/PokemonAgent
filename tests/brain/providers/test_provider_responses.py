"""provider 响应映射契约：token 字段落位、truncated 判据与空正文的显式异常。"""

from __future__ import annotations

import pytest
from _doubles.http import FakeUrlopen, ok_body

from pokemon_agent.brain.errors import EmptyCompletion
from pokemon_agent.brain.providers import QwenProvider
from pokemon_agent.brain.schemas import LlmCompleteReq

KEY_VARS = ("DASHSCOPE_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ARK_API_KEY", "DEEPSEEK_API_KEY")


@pytest.fixture(autouse=True)
def _no_keys_in_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """每个测试先把四个 key 变量全清掉，不依赖机器上的真实环境。"""

    for name in KEY_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def provider(monkeypatch: pytest.MonkeyPatch) -> QwenProvider:
    """一个带 key 的 Qwen provider。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    return QwenProvider(temperature=0.0)


@pytest.fixture()
def fake_urlopen(monkeypatch: pytest.MonkeyPatch) -> FakeUrlopen:
    """把共享替身装到 ``urllib.request.urlopen`` 上。"""

    fake = FakeUrlopen()
    monkeypatch.setattr("urllib.request.urlopen", fake)
    return fake


def test_every_token_number_lands_on_its_own_response_field(
    provider: QwenProvider, fake_urlopen: FakeUrlopen
) -> None:
    """完整 usage：文本与四个 token 数各落各位。"""

    fake_urlopen.next_body = ok_body()

    resp = provider.complete(LlmCompleteReq(prompt="hi"))

    assert resp.text == "hi"
    assert resp.prompt_tokens == 11
    assert resp.completion_tokens == 5
    assert resp.cached_tokens == 3
    assert resp.reasoning_tokens == 2
    assert resp.truncated is False


def test_a_response_without_usage_yields_all_zero_counters(
    provider: QwenProvider, fake_urlopen: FakeUrlopen
) -> None:
    """没有 usage 时四个数字全是 0，不炸。"""

    fake_urlopen.next_body = {"choices": [{"message": {"content": "x"}, "finish_reason": "stop"}]}

    resp = provider.complete(LlmCompleteReq(prompt="hi"))

    assert resp.text == "x"
    assert resp.prompt_tokens == 0
    assert resp.completion_tokens == 0
    assert resp.cached_tokens == 0
    assert resp.reasoning_tokens == 0
    assert resp.truncated is False


def test_truncated_follows_the_finish_reason_length(
    provider: QwenProvider, fake_urlopen: FakeUrlopen
) -> None:
    """finish_reason="length" → truncated=True。"""

    fake_urlopen.next_body = ok_body(finish="length")

    resp = provider.complete(LlmCompleteReq(prompt="hi"))

    assert resp.truncated is True


def test_hitting_the_token_cap_with_a_stop_finish_reason_is_not_truncated(
    provider: QwenProvider, fake_urlopen: FakeUrlopen
) -> None:
    """finish_reason="stop" 且恰好写满 25600：不算截断。

    判据是服务端的 finish_reason，不是 token 数。
    """

    fake_urlopen.next_body = ok_body(finish="stop", completion_tokens=25600)

    resp = provider.complete(LlmCompleteReq(prompt="hi"))

    assert resp.truncated is False
    assert resp.completion_tokens == 25600


@pytest.mark.parametrize("content", ["", None, "   "])
def test_an_empty_body_raises_empty_completion_with_the_counters(
    content: str | None, provider: QwenProvider, fake_urlopen: FakeUrlopen
) -> None:
    """空正文（空串、None、纯空白）抛 EmptyCompletion，并带出 token 数与 finish_reason。"""

    fake_urlopen.next_body = ok_body(text=content, finish=None)

    with pytest.raises(EmptyCompletion) as exc_info:
        provider.complete(LlmCompleteReq(prompt="hi"))

    assert exc_info.value.completion_tokens == 5
    assert exc_info.value.reasoning_tokens == 2
    assert exc_info.value.finish_reason == ""


def test_an_empty_body_keeps_the_server_finish_reason(
    provider: QwenProvider, fake_urlopen: FakeUrlopen
) -> None:
    """finish_reason 存在时，EmptyCompletion 原样带出它。"""

    fake_urlopen.next_body = ok_body(text="", finish="length")

    with pytest.raises(EmptyCompletion) as exc_info:
        provider.complete(LlmCompleteReq(prompt="hi"))

    assert exc_info.value.finish_reason == "length"
    assert exc_info.value.completion_tokens == 5
