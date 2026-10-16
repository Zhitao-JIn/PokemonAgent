"""``describe()`` 的请求形状与响应映射：文字块在前图在后、字段落位、超时与失败分类。"""

from __future__ import annotations

from typing import Any
from urllib.error import HTTPError

import pytest
from _doubles.http import FakeUrlopen

from pokemon_agent.brain.errors import EmptyCompletion, ProviderRejected, ToolTimeout
from pokemon_agent.brain.providers import (
    ArkProvider,
    DeepSeekProvider,
    QwenProvider,
)
from pokemon_agent.brain.schemas import VisionDescribeReq

KEY_VARS = ("DASHSCOPE_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ARK_API_KEY", "DEEPSEEK_API_KEY")

VENDOR_ENV = {
    "qwen": "DASHSCOPE_API_KEY",
    "ark": "ARK_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}
VENDOR_URL = {
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    "ark": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
    "deepseek": "https://api.deepseek.com/chat/completions",
}


def make(vendor: str, **kwargs: Any) -> Any:
    """三家构造统一入口：Ark 的 model 是位置必填。"""

    if vendor == "qwen":
        return QwenProvider(**kwargs)
    if vendor == "ark":
        return ArkProvider(kwargs.pop("model", "doubao-x"), **kwargs)
    return DeepSeekProvider(**kwargs)


def io_error(code: int) -> HTTPError:
    import io

    return HTTPError("url", code, "reason", None, io.BytesIO(b"upstream body"))


@pytest.fixture(autouse=True)
def _no_keys_in_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """每个测试先把四个 key 变量全清掉，不依赖机器上的真实环境。"""

    for name in KEY_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def fake_urlopen(monkeypatch: pytest.MonkeyPatch) -> FakeUrlopen:
    """装好替身，且默认响应的 prompt_tokens 足够大（不触发丢图检测）。"""

    fake = FakeUrlopen()
    fake.next_body = {
        "choices": [{"message": {"content": "seen"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 3},
    }
    monkeypatch.setattr("urllib.request.urlopen", fake)
    return fake


@pytest.mark.parametrize("vendor", ["qwen", "deepseek"])
@pytest.mark.parametrize("images_count", [1, 3])
def test_the_content_leads_with_the_text_block_then_the_images_in_order_verbatim(
    vendor: str, images_count: int, monkeypatch: pytest.MonkeyPatch, fake_urlopen: FakeUrlopen
) -> None:
    """文字块在最前，其后按 req.images 顺序排 image_url，url 原样透传。"""

    monkeypatch.setenv(VENDOR_ENV[vendor], "sk-x")
    provider = make(vendor, temperature=0.0)
    frames = [f"data:image/png;base64,frame{i}" for i in range(images_count)]

    provider.describe(VisionDescribeReq(images=frames, prompt="Q"))
    content = fake_urlopen.calls[0]["json"]["messages"][0]["content"]

    assert content[0] == {"type": "text", "text": "Q"}
    image_blocks = content[1:]

    assert [block["image_url"]["url"] for block in image_blocks] == frames


@pytest.mark.parametrize("vendor", ["qwen", "ark", "deepseek"])
def test_a_describe_request_lands_on_the_same_endpoint_with_bearer_auth(
    vendor: str, monkeypatch: pytest.MonkeyPatch, fake_urlopen: FakeUrlopen
) -> None:
    """describe 的请求落在 base_url + /chat/completions，带 Bearer（每家一条）。"""

    monkeypatch.setenv(VENDOR_ENV[vendor], "sk-x")
    provider = make(vendor, temperature=0.0)

    provider.describe(VisionDescribeReq(images=["data:image/png;base64,AAA"], prompt="Q"))

    assert fake_urlopen.calls[0]["url"] == VENDOR_URL[vendor]
    assert fake_urlopen.calls[0]["headers"]["authorization"] == "Bearer sk-x"


@pytest.mark.parametrize("vendor", ["qwen", "ark", "deepseek"])
def test_the_four_token_counters_land_on_the_describe_response(
    vendor: str, monkeypatch: pytest.MonkeyPatch, fake_urlopen: FakeUrlopen
) -> None:
    """完整 usage：文本与四个 token 数落到 VisionDescribeResp（三家参数化）。"""

    monkeypatch.setenv(VENDOR_ENV[vendor], "sk-x")
    provider = make(vendor, temperature=0.0)
    fake_urlopen.next_body = {
        "choices": [{"message": {"content": "seen"}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": 1000,
            "completion_tokens": 3,
            "prompt_tokens_details": {"cached_tokens": 4},
            "completion_tokens_details": {"reasoning_tokens": 2},
        },
    }

    resp = provider.describe(VisionDescribeReq(images=["data:image/png;base64,AAA"], prompt="Q"))

    assert resp.text == "seen"
    assert resp.input_tokens == 1000
    assert resp.output_tokens == 3
    assert resp.cached_tokens == 4
    assert resp.reasoning_tokens == 2


def test_an_empty_prompt_is_rejected_before_any_request(
    monkeypatch: pytest.MonkeyPatch, fake_urlopen: FakeUrlopen
) -> None:
    """空 prompt 在发出请求之前就被 assert 拒掉，替身一次都没被调。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    provider = QwenProvider(temperature=0.0)

    with pytest.raises(AssertionError, match="empty prompt"):
        provider.describe(VisionDescribeReq(images=["data:image/png;base64,AAA"], prompt=""))

    assert fake_urlopen.call_count == 0


@pytest.mark.parametrize("content", ["", None, "   "])
def test_an_empty_describe_body_raises_empty_completion(
    content: str | None, monkeypatch: pytest.MonkeyPatch, fake_urlopen: FakeUrlopen
) -> None:
    """空正文（空串、None、纯空白）→ EmptyCompletion。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    provider = QwenProvider(temperature=0.0)
    fake_urlopen.next_body = {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 1},
    }

    with pytest.raises(EmptyCompletion):
        provider.describe(VisionDescribeReq(images=["data:image/png;base64,AAA"], prompt="Q"))


def test_a_per_call_timeout_s_overrides_this_describe_only(
    monkeypatch: pytest.MonkeyPatch, fake_urlopen: FakeUrlopen
) -> None:
    """timeout_s 只覆盖这一次，下一次不带又回到构造时的值。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    provider = QwenProvider(temperature=0.0, timeout=9)
    request = VisionDescribeReq(images=["data:image/png;base64,AAA"], prompt="Q")

    provider.describe(request, timeout_s=3.5)
    provider.describe(request)

    assert fake_urlopen.calls[0]["timeout"] == 3.5
    assert fake_urlopen.calls[1]["timeout"] == 9


def test_a_non_positive_timeout_s_is_rejected_before_any_request(
    monkeypatch: pytest.MonkeyPatch, fake_urlopen: FakeUrlopen
) -> None:
    """timeout_s 为 0 → ValueError，请求根本没发出去。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    provider = QwenProvider(temperature=0.0)

    with pytest.raises(ValueError, match="timeout_s must be positive"):
        provider.describe(
            VisionDescribeReq(images=["data:image/png;base64,AAA"], prompt="Q"), timeout_s=0
        )

    assert fake_urlopen.call_count == 0


@pytest.mark.parametrize(
    ("exc", "expected_exc"),
    [
        (io_error(401), ProviderRejected),
        (io_error(503), ToolTimeout),
    ],
)
def test_describe_failures_follow_the_same_classification_as_complete(
    exc: Exception,
    expected_exc: type,
    monkeypatch: pytest.MonkeyPatch,
    fake_urlopen: FakeUrlopen,
) -> None:
    """HTTP 401 → ProviderRejected、503 → ToolTimeout，且一次调用一个请求。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    provider = QwenProvider(temperature=0.0)
    fake_urlopen.next_exc = exc

    with pytest.raises(expected_exc):
        provider.describe(VisionDescribeReq(images=["data:image/png;base64,AAA"], prompt="Q"))

    assert fake_urlopen.call_count == 1


def test_describe_sends_the_thinking_field_from_the_constructor_only(
    monkeypatch: pytest.MonkeyPatch, fake_urlopen: FakeUrlopen
) -> None:
    """describe 不带 thinking 覆盖：构造时开则请求体开、缺省则关（Qwen 一对）。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    on = QwenProvider(temperature=0.0, thinking=True)
    off = QwenProvider(temperature=0.0)
    request = VisionDescribeReq(images=["data:image/png;base64,AAA"], prompt="Q")

    on.describe(request)
    off.describe(request)

    assert fake_urlopen.calls[0]["json"]["enable_thinking"] is True
    assert fake_urlopen.calls[1]["json"]["enable_thinking"] is False


def test_the_truncation_marker_reaches_the_describe_response(
    monkeypatch: pytest.MonkeyPatch, fake_urlopen: FakeUrlopen
) -> None:
    """finish_reason="length" → `truncated is True`；"stop" → False（O16）。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    provider = QwenProvider(temperature=0.0)
    request = VisionDescribeReq(images=["data:image/png;base64,AAA"], prompt="Q")

    fake_urlopen.next_body = {
        "choices": [{"message": {"content": "cut"}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 25600},
    }
    truncated = provider.describe(request)

    fake_urlopen.next_body = {
        "choices": [{"message": {"content": "done"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 3},
    }
    complete = provider.describe(request)

    assert truncated.truncated is True
    assert complete.truncated is False
