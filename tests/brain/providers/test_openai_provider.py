"""OpenAI 请求、usage 与错误分类契约；全部 HTTP 使用替身。"""

from __future__ import annotations

from urllib.error import URLError

import pytest
from _doubles.http import FakeUrlopen, ok_body

from pokemon_agent.brain.errors import EmptyCompletion, ProviderRejected, ToolTimeout
from pokemon_agent.brain.providers import OpenAIProvider, provider_for
from pokemon_agent.brain.schemas import LlmCompleteReq, VisionDescribeReq


@pytest.fixture(autouse=True)
def fake_urlopen(monkeypatch: pytest.MonkeyPatch) -> FakeUrlopen:
    """隔离本机密钥和网络。"""
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-secret")
    fake = FakeUrlopen()
    monkeypatch.setattr("urllib.request.urlopen", fake)
    return fake


@pytest.mark.parametrize("thinking", [False, True])
@pytest.mark.parametrize("effort", ["none", "low", "medium", "high", "xhigh", "max"])
def test_request_uses_native_token_limit_effort_and_temperature_rules(
    thinking: bool, effort: str, fake_urlopen: FakeUrlopen
) -> None:
    provider = OpenAIProvider(temperature=0.3, max_tokens=77, thinking=thinking, effort=effort)

    provider.complete(LlmCompleteReq(prompt="hi"))

    call = fake_urlopen.calls[0]
    body = call["json"]
    assert call["url"] == "https://api.openai.com/v1/chat/completions"
    assert call["headers"] == {
        "content-type": "application/json",
        "authorization": "Bearer fake-openai-secret",
    }
    assert body["max_completion_tokens"] == 77
    assert "max_tokens" not in body
    assert body["reasoning_effort"] == (effort if thinking else "none")
    sent = not thinking or effort == "none"
    assert ("temperature" in body) is sent
    if sent:
        assert body["temperature"] == 0.3
    assert "thinking" not in body
    assert "cache_control" not in body
    assert provider.config()["temperature_sent"] == str(sent).lower()
    assert "fake-openai-secret" not in str(provider.config())


def test_default_effort_and_per_call_override_preserve_json_mode(fake_urlopen: FakeUrlopen) -> None:
    provider = OpenAIProvider(temperature=0.0, thinking=True, json_mode=True)

    provider.complete(LlmCompleteReq(prompt="JSON please"))
    provider.complete(LlmCompleteReq(prompt="JSON please", thinking=False))

    first, second = [call["json"] for call in fake_urlopen.calls]
    assert first["reasoning_effort"] == "medium"
    assert "temperature" not in first
    assert second["reasoning_effort"] == "none"
    assert second["temperature"] == 0.0
    assert first["response_format"] == second["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize("effort", ["minimal", "invalid", ""])
def test_invalid_effort_fails_at_construction(effort: str) -> None:
    with pytest.raises(ValueError, match="invalid OpenAI effort"):
        OpenAIProvider(temperature=0.0, effort=effort)


@pytest.mark.parametrize("finish", ["length", "stop"])
def test_shared_unpack_maps_usage_and_truncation(finish: str, fake_urlopen: FakeUrlopen) -> None:
    fake_urlopen.next_body = ok_body(finish=finish)

    response = OpenAIProvider(temperature=0.0).complete(LlmCompleteReq(prompt="hi"))

    assert response.text == "hi"
    assert response.prompt_tokens == 11
    assert response.completion_tokens == 5
    assert response.cached_tokens == 3
    assert response.reasoning_tokens == 2
    assert response.truncated is (finish == "length")


def test_empty_body_raises_shared_error(fake_urlopen: FakeUrlopen) -> None:
    fake_urlopen.next_body = ok_body(text="", finish="length")

    with pytest.raises(EmptyCompletion):
        OpenAIProvider(temperature=0.0).complete(LlmCompleteReq(prompt="hi"))


def test_multiple_images_keep_default_image_url_blocks(fake_urlopen: FakeUrlopen) -> None:
    fake_urlopen.next_body = ok_body(prompt_tokens=300)
    images = ["data:image/png;base64,cG5n", "data:image/png;base64,cG5nMg=="]

    OpenAIProvider(temperature=0.0).describe(VisionDescribeReq(prompt="look", images=images))

    assert fake_urlopen.calls[0]["json"]["messages"][0]["content"] == [
        {"type": "text", "text": "look"},
        *[{"type": "image_url", "image_url": {"url": image}} for image in images],
    ]


@pytest.mark.parametrize("code", [400, 401, 403, 404, 429, 500, 503])
def test_http_errors_reuse_shared_classification(code: int, fake_urlopen: FakeUrlopen) -> None:
    fake_urlopen.http_error(code)
    error = ProviderRejected if 400 <= code < 500 and code != 429 else ToolTimeout

    with pytest.raises(error, match=f"OpenAIProvider HTTP {code}") as caught:
        OpenAIProvider(temperature=0.0).complete(LlmCompleteReq(prompt="hi"))

    assert fake_urlopen.call_count == 1
    assert "fake-openai-secret" not in str(caught.value)


def test_network_failure_is_timeout(fake_urlopen: FakeUrlopen) -> None:
    fake_urlopen.next_exc = URLError("dns")

    with pytest.raises(ToolTimeout):
        OpenAIProvider(temperature=0.0).complete(LlmCompleteReq(prompt="hi"))


def test_key_has_no_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "wrong-key")

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        OpenAIProvider(temperature=0.0)


def test_default_request_keeps_single_user_message(fake_urlopen: FakeUrlopen) -> None:
    provider = OpenAIProvider(temperature=0.0)

    provider.complete(LlmCompleteReq(prompt="rules<tail>dynamic"))

    assert fake_urlopen.calls[0]["json"]["messages"] == [
        {"role": "user", "content": "rules<tail>dynamic"}
    ]


def test_cache_marker_splits_text_once(fake_urlopen: FakeUrlopen) -> None:
    provider = OpenAIProvider(temperature=0.0, cache_marker="<tail>")

    provider.complete(LlmCompleteReq(prompt="rules<tail>one<tail>two"))

    assert fake_urlopen.calls[0]["json"]["messages"] == [
        {"role": "developer", "content": "rules"},
        {"role": "user", "content": "<tail>one<tail>two"},
    ]


def test_cache_marker_keeps_images_in_user_message_in_order(fake_urlopen: FakeUrlopen) -> None:
    fake_urlopen.next_body = ok_body(prompt_tokens=300)
    images = ["data:image/png;base64,Zmlyc3Q=", "data:image/png;base64,c2Vjb25k"]
    provider = OpenAIProvider(temperature=0.0, cache_marker="<tail>", image_detail="high")

    provider.describe(VisionDescribeReq(prompt="rules<tail>dynamic", images=images))

    assert fake_urlopen.calls[0]["json"]["messages"] == [
        {"role": "developer", "content": "rules"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "<tail>dynamic"},
                *[
                    {"type": "image_url", "image_url": {"url": image, "detail": "high"}}
                    for image in images
                ],
            ],
        },
    ]


@pytest.mark.parametrize(
    "marker,prompt",
    [
        (None, "rules<tail>dynamic"),
        ("<tail>", "rules without marker"),
        ("<tail>", "<tail>dynamic"),
        ("", "rules<tail>dynamic"),
    ],
)
def test_marker_absent_or_at_position_zero_keeps_single_message(
    marker: str | None, prompt: str, fake_urlopen: FakeUrlopen
) -> None:
    provider = OpenAIProvider(temperature=0.0, cache_marker=marker)

    provider.complete(LlmCompleteReq(prompt=prompt))

    assert fake_urlopen.calls[0]["json"]["messages"] == [{"role": "user", "content": prompt}]


def test_image_detail_is_added_to_every_image_url(fake_urlopen: FakeUrlopen) -> None:
    fake_urlopen.next_body = ok_body(prompt_tokens=300)
    images = ["data:image/png;base64,Zmlyc3Q=", "data:image/png;base64,c2Vjb25k"]
    provider = OpenAIProvider(temperature=0.0, image_detail="original")

    provider.describe(VisionDescribeReq(prompt="look", images=images))

    assert fake_urlopen.calls[0]["json"]["messages"][0]["content"] == [
        {"type": "text", "text": "look"},
        *[
            {"type": "image_url", "image_url": {"url": image, "detail": "original"}}
            for image in images
        ],
    ]


@pytest.mark.parametrize("detail", ["lowest", "medium", "", "HIGH"])
def test_invalid_image_detail_fails_at_construction(detail: str) -> None:
    with pytest.raises(ValueError, match="invalid OpenAI image detail"):
        OpenAIProvider(temperature=0.0, image_detail=detail)


def test_config_reports_cache_marker_with_empty_default(fake_urlopen: FakeUrlopen) -> None:
    assert OpenAIProvider(temperature=0.0, cache_marker="<tail>").config()["cache_marker"] == (
        "<tail>"
    )
    assert OpenAIProvider(temperature=0.0).config()["cache_marker"] == ""


def test_prefix_selects_openai_and_unknown_error_lists_it() -> None:
    assert isinstance(provider_for("gpt-6-luna", temperature=0.0), OpenAIProvider)
    with pytest.raises(ValueError, match="gpt-"):
        provider_for("unknown-model", temperature=0.0)
