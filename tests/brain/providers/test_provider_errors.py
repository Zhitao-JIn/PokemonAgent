"""provider 失败分类契约：4xx/5xx/网络层的异常归属、一次一请求、总时长闸与 key 不泄漏。"""

from __future__ import annotations

import time
from typing import Any
from urllib.error import HTTPError, URLError

import pytest
from _doubles.http import BlockingUrlopen, FakeUrlopen

from pokemon_agent.brain.errors import ProviderRejected, ToolTimeout
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

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-unique-secret-123")
    return QwenProvider(temperature=0.0)


@pytest.fixture()
def fake_urlopen(monkeypatch: pytest.MonkeyPatch) -> FakeUrlopen:
    """把共享替身装到 ``urllib.request.urlopen`` 上。"""

    fake = FakeUrlopen()
    monkeypatch.setattr("urllib.request.urlopen", fake)
    return fake


def _raise_http_error(fake: FakeUrlopen, code: int, body: str = "upstream body") -> None:
    fake.next_exc = HTTPError("url", code, "reason", None, _bytes_io(body))


def _bytes_io(text: str) -> Any:
    import io

    return io.BytesIO(text.encode())


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_a_4xx_is_a_provider_rejected_with_code_and_body(
    code: int, provider: QwenProvider, fake_urlopen: FakeUrlopen
) -> None:
    """4xx（400/401/403/404）→ ProviderRejected，消息含 provider 类名、状态码与响应体。"""

    _raise_http_error(fake_urlopen, code, body="upstream body")

    with pytest.raises(ProviderRejected, match=f"QwenProvider HTTP {code}: upstream body"):
        provider.complete(LlmCompleteReq(prompt="hi"))


@pytest.mark.parametrize("code", [500, 502, 503])
def test_a_5xx_is_a_tool_timeout_with_code_and_body(
    code: int, provider: QwenProvider, fake_urlopen: FakeUrlopen
) -> None:
    """5xx（500/502/503）→ ToolTimeout（值得再试），消息含类名、状态码与响应体。"""

    _raise_http_error(fake_urlopen, code, body="upstream body")

    with pytest.raises(ToolTimeout, match=f"QwenProvider HTTP {code}: upstream body"):
        provider.complete(LlmCompleteReq(prompt="hi"))


@pytest.mark.parametrize(
    "exc",
    [URLError("dns gone"), ConnectionResetError("reset"), TimeoutError("socket timed out")],
    ids=["URLError", "ConnectionResetError", "TimeoutError"],
)
def test_a_network_level_failure_is_a_tool_timeout_naming_the_exception(
    exc: Exception, provider: QwenProvider, fake_urlopen: FakeUrlopen
) -> None:
    """网络层异常（URLError/ConnectionResetError/TimeoutError）→ ToolTimeout，消息带异常类名。"""

    fake_urlopen.next_exc = exc

    with pytest.raises(ToolTimeout, match=f"QwenProvider 调用不通：{type(exc).__name__}"):
        provider.complete(LlmCompleteReq(prompt="hi"))


@pytest.mark.parametrize("code", [503, 401])
def test_one_complete_call_sends_exactly_one_http_request(
    code: int, provider: QwenProvider, fake_urlopen: FakeUrlopen
) -> None:
    """一次调用一个请求：provider 层不重试，失败也只发一次。"""

    _raise_http_error(fake_urlopen, code)

    with pytest.raises((ToolTimeout, ProviderRejected)):
        provider.complete(LlmCompleteReq(prompt="hi"))

    assert fake_urlopen.call_count == 1


def test_a_blocked_request_hits_the_wall_clock_within_two_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """单请求总时长硬闸：urlopen 一直阻塞，timeout_s=0.2 也要在约 2 秒内抛 ToolTimeout。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    provider = QwenProvider(temperature=0.0)
    fake = BlockingUrlopen()
    monkeypatch.setattr("urllib.request.urlopen", fake)

    started = time.monotonic()
    try:
        with pytest.raises(ToolTimeout, match="QwenProvider 调用不通"):
            provider.complete(LlmCompleteReq(prompt="hi"), timeout_s=0.2)
    finally:
        fake.release.set()

    elapsed = time.monotonic() - started

    assert elapsed < 2.0, f"阻塞请求 {elapsed:.2f}s 才抛，总时长闸没兜住"


@pytest.mark.parametrize("code", [401, 503])
def test_the_api_key_never_leaks_into_error_messages(
    code: int, provider: QwenProvider, fake_urlopen: FakeUrlopen
) -> None:
    """401 与 503 的错误消息里既没有 key 的值也没有 Bearer。"""

    _raise_http_error(fake_urlopen, code, body="upstream body")

    with pytest.raises((ProviderRejected, ToolTimeout)) as exc_info:
        provider.complete(LlmCompleteReq(prompt="hi"))

    message = str(exc_info.value)

    assert "sk-unique-secret-123" not in message
    assert "Bearer" not in message


def test_a_rate_limit_429_is_a_retryable_tool_timeout(
    provider: QwenProvider, fake_urlopen: FakeUrlopen
) -> None:
    """429 是瞬时限流，等一等往往能成功——归 ToolTimeout（值得在预算内重试）。

    其余 4xx 仍是 ProviderRejected（配置/请求错误，重试注定无用）。
    """

    _raise_http_error(fake_urlopen, 429, body="rate limited")

    with pytest.raises(ToolTimeout, match="QwenProvider HTTP 429: rate limited"):
        provider.complete(LlmCompleteReq(prompt="hi"))

    assert fake_urlopen.call_count == 1
