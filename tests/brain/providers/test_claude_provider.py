"""Claude 原生请求、响应与共用传输契约；全部 HTTP 使用替身。"""

from __future__ import annotations

import time
from urllib.error import URLError
from urllib.request import Request

import pytest
from _doubles.http import BlockingUrlopen, FakeUrlopen

from pokemon_agent.brain.errors import EmptyCompletion, ProviderRejected, ToolTimeout
from pokemon_agent.brain.providers import ClaudeProvider, QwenProvider, provider_for
from pokemon_agent.brain.schemas import LlmCompleteReq, VisionDescribeReq


@pytest.fixture(autouse=True)
def fake_urlopen(monkeypatch: pytest.MonkeyPatch) -> FakeUrlopen:
    """隔离本机密钥与网络，默认返回原生 Messages 响应。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-claude-secret")
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    fake = FakeUrlopen(
        body={
            "content": [{"type": "text", "text": "answer"}],
            "usage": {"input_tokens": 300, "output_tokens": 7},
            "stop_reason": "end_turn",
        }
    )
    monkeypatch.setattr("urllib.request.urlopen", fake)
    return fake


def test_native_request_omits_sampling_and_keeps_key_out_of_config(
    fake_urlopen: FakeUrlopen,
) -> None:
    provider = ClaudeProvider(temperature=0.3, max_tokens=77, json_mode=True)

    provider.complete(LlmCompleteReq(prompt="hi"), timeout_s=0.5)

    call = fake_urlopen.calls[0]
    assert call["url"] == "https://api.anthropic.com/v1/messages"
    assert call["headers"] == {
        "content-type": "application/json",
        "x-api-key": "fake-claude-secret",
        "anthropic-version": "2023-06-01",
    }
    assert call["timeout"] == 0.5
    assert call["json"] == {
        "model": "claude-haiku-5-5",
        "max_tokens": 77,
        "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
        "thinking": {"type": "disabled"},
    }
    assert provider.config()["temperature_sent"] == "false"
    assert "fake-claude-secret" not in str(provider.config())


def test_auth_token_is_not_a_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "wrong-key")

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        ClaudeProvider(temperature=0.0)


@pytest.mark.parametrize("marker", [None, "missing", "", "rules"])
def test_no_cache_block_without_a_nonempty_static_prefix(
    marker: str | None, fake_urlopen: FakeUrlopen
) -> None:
    provider = ClaudeProvider(temperature=0.0, cache_marker=marker)

    provider.complete(LlmCompleteReq(prompt="rules dynamic"))

    assert fake_urlopen.calls[0]["json"]["messages"][0]["content"] == [
        {"type": "text", "text": "rules dynamic"}
    ]


def test_cache_marker_splits_once_and_images_stay_after_text(fake_urlopen: FakeUrlopen) -> None:
    provider = ClaudeProvider(temperature=0.0, cache_marker="<dynamic>")

    provider.describe(
        VisionDescribeReq(
            prompt="rules<dynamic>one<dynamic>two",
            images=["data:image/png;base64,Zmlyc3Q=", "data:image/png;base64,c2Vjb25k"],
        )
    )

    assert fake_urlopen.calls[0]["json"]["messages"][0]["content"] == [
        {"type": "text", "text": "rules", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "<dynamic>one<dynamic>two"},
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": "Zmlyc3Q="},
        },
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": "c2Vjb25k"},
        },
    ]


@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max"])
def test_adaptive_thinking_sends_effort_in_output_config(
    effort: str, fake_urlopen: FakeUrlopen
) -> None:
    provider = ClaudeProvider(temperature=0.0, thinking=True, effort=effort)

    provider.complete(LlmCompleteReq(prompt="hi"))

    body = fake_urlopen.calls[0]["json"]
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"] == {"effort": effort}
    assert "effort" not in body
    assert "budget_tokens" not in str(body)


def test_default_effort_is_high_and_per_call_thinking_can_disable_it(
    fake_urlopen: FakeUrlopen,
) -> None:
    provider = ClaudeProvider(temperature=0.0, thinking=True)

    provider.complete(LlmCompleteReq(prompt="hi"))
    provider.complete(LlmCompleteReq(prompt="hi", thinking=False))

    assert fake_urlopen.calls[0]["json"]["output_config"] == {"effort": "high"}
    assert fake_urlopen.calls[1]["json"]["thinking"] == {"type": "disabled"}
    assert "output_config" not in fake_urlopen.calls[1]["json"]


def test_invalid_effort_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="invalid Claude effort"):
        ClaudeProvider(temperature=0.0, effort="unknown")


def test_single_image_and_missing_usage_use_native_defaults(fake_urlopen: FakeUrlopen) -> None:
    fake_urlopen.next_body = {"content": [{"type": "text", "text": "answer"}]}
    provider = ClaudeProvider(temperature=0.0, token_floor=0)

    response = provider.describe(
        VisionDescribeReq(prompt="look", images=["data:image/png;base64,cG5n"])
    )

    assert fake_urlopen.calls[0]["json"]["messages"][0]["content"] == [
        {"type": "text", "text": "look"},
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": "cG5n"},
        },
    ]
    assert response.input_tokens == 0
    assert response.output_tokens == 0
    assert response.cached_tokens == 0
    assert response.reasoning_tokens == 0
    assert response.truncated is False


@pytest.mark.parametrize("finish", ["end_turn", "max_tokens"])
def test_text_blocks_usage_and_truncation_are_mapped(
    finish: str, fake_urlopen: FakeUrlopen
) -> None:
    fake_urlopen.next_body = {
        "content": [
            {"type": "thinking", "thinking": "hidden"},
            {"type": "text", "text": "first"},
            {"type": "text", "text": "second"},
        ],
        "usage": {
            "input_tokens": 11,
            "cache_read_input_tokens": 13,
            "cache_creation_input_tokens": 17,
            "output_tokens": 7,
        },
        "stop_reason": finish,
    }
    provider = ClaudeProvider(temperature=0.0)

    response = provider.complete(LlmCompleteReq(prompt="hi"))

    assert response.text == "firstsecond"
    assert response.prompt_tokens == 41
    assert response.cached_tokens == 13
    assert response.completion_tokens == 7
    assert response.reasoning_tokens == 0
    assert response.truncated is (finish == "max_tokens")


@pytest.mark.parametrize("text", ["", "  "])
def test_empty_text_raises_even_when_thinking_consumed_the_token_cap(
    text: str, fake_urlopen: FakeUrlopen
) -> None:
    fake_urlopen.next_body["content"] = [
        {"type": "thinking", "thinking": "hidden"},
        {"type": "text", "text": text},
    ]
    fake_urlopen.next_body["stop_reason"] = "max_tokens"

    with pytest.raises(EmptyCompletion):
        ClaudeProvider(temperature=0.0).complete(LlmCompleteReq(prompt="hi"))


@pytest.mark.parametrize("code", [400, 401, 403, 404, 429, 500, 503])
def test_http_errors_share_existing_classification(code: int, fake_urlopen: FakeUrlopen) -> None:
    fake_urlopen.http_error(code)
    error_type = ProviderRejected if 400 <= code < 500 and code != 429 else ToolTimeout

    with pytest.raises(error_type, match=f"ClaudeProvider HTTP {code}") as caught:
        ClaudeProvider(temperature=0.0).complete(LlmCompleteReq(prompt="hi"))

    assert fake_urlopen.call_count == 1
    assert "fake-claude-secret" not in str(caught.value)


@pytest.mark.parametrize("error", [URLError("dns"), TimeoutError("socket"), OSError("network")])
def test_network_errors_are_timeouts(error: Exception, fake_urlopen: FakeUrlopen) -> None:
    fake_urlopen.next_exc = error

    with pytest.raises(ToolTimeout, match="ClaudeProvider"):
        ClaudeProvider(temperature=0.0).complete(LlmCompleteReq(prompt="hi"))


def test_blocked_request_hits_total_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = BlockingUrlopen()
    monkeypatch.setattr("urllib.request.urlopen", fake)
    provider = ClaudeProvider(temperature=0.0)

    started = time.monotonic()
    try:
        with pytest.raises(ToolTimeout):
            provider.complete(LlmCompleteReq(prompt="hi"), timeout_s=0.1)
    finally:
        fake.release.set()

    assert time.monotonic() - started < 2.0


def test_provider_selection_and_unknown_prefix_message() -> None:
    provider = provider_for("claude-haiku-5-5", temperature=0.0)

    assert isinstance(provider, ClaudeProvider)
    with pytest.raises(ValueError, match="claude-"):
        provider_for("unknown-model", temperature=0.0)


def test_qwen_request_matches_existing_request_contract(
    monkeypatch: pytest.MonkeyPatch, fake_urlopen: FakeUrlopen
) -> None:
    """沿用 test_provider_request 的 URL、头与正文断言，并核对请求字节。"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    provider = QwenProvider(temperature=0.3, max_tokens=77)
    fake_urlopen.next_body = {"choices": [{"message": {"content": "hi"}}]}
    sent: list[bytes | None] = []

    def capture(request: Request, timeout: float | None = None) -> object:
        sent.append(request.data)
        return fake_urlopen(request, timeout=timeout)

    monkeypatch.setattr("urllib.request.urlopen", capture)

    provider.complete(LlmCompleteReq(prompt="hi"))

    call = fake_urlopen.calls[0]
    assert call["url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    assert call["headers"] == {"content-type": "application/json", "authorization": "Bearer sk-q"}
    assert call["json"] == {
        "model": provider.config()["model"],
        "temperature": 0.3,
        "max_tokens": 77,
        "messages": [{"role": "user", "content": "hi"}],
        "enable_thinking": False,
    }
    assert sent == [
        b'{"model": "qwen3.8-max", "temperature": 0.3, "max_tokens": 77, '
        b'"messages": [{"role": "user", "content": "hi"}], "enable_thinking": false}'
    ]
