"""静默丢图检测（floor）契约：门槛随实际发出的图片数放大、Ark 不放大、异常带账。"""

from __future__ import annotations

from typing import Any

import pytest
from _doubles.frames import solid_frame
from _doubles.http import FakeUrlopen

from pokemon_agent.brain.errors import ImageNotDelivered
from pokemon_agent.brain.providers import (
    IMAGE_TOKEN_FLOOR,
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

FRAME = "data:image/png;base64,AAA"
"""Qwen/DeepSeek 用的占位帧：它们不解码帧内容，形状对就行。

Ark 会把多帧解码拼成网格图，用它的测试一律换真帧（`solid_frame`）。
"""


def make(vendor: str, **kwargs: Any) -> Any:
    """三家构造统一入口：Ark 的 model 是位置必填。"""

    if vendor == "qwen":
        return QwenProvider(**kwargs)
    if vendor == "ark":
        return ArkProvider(kwargs.pop("model", "doubao-x"), **kwargs)
    return DeepSeekProvider(**kwargs)


def with_prompt_tokens(fake: FakeUrlopen, tokens: int) -> None:
    """让服务端报回指定的 prompt_tokens——丢图检测的唯一输入。"""

    fake.next_body = {
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": tokens, "completion_tokens": 1},
    }


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
    ("vendor", "image_count", "prompt_tokens", "delivered"),
    [
        ("qwen", 1, 99, False),
        ("qwen", 1, 100, True),
        ("qwen", 3, 299, False),
        ("qwen", 3, 300, True),
        ("deepseek", 1, 99, False),
        ("deepseek", 1, 100, True),
        ("deepseek", 3, 299, False),
        ("deepseek", 3, 300, True),
    ],
)
def test_the_floor_boundary_scales_with_the_image_count_for_qwen_and_deepseek(
    vendor: str,
    image_count: int,
    prompt_tokens: int,
    delivered: bool,
    monkeypatch: pytest.MonkeyPatch,
    fake_urlopen: FakeUrlopen,
) -> None:
    """Qwen 与 DeepSeek：N 张图的门槛是 N×token_floor，报回少 1 抛、恰好够过。"""

    monkeypatch.setenv(VENDOR_ENV[vendor], "sk-x")
    provider = make(vendor, temperature=0.0)
    with_prompt_tokens(fake_urlopen, prompt_tokens)
    request = VisionDescribeReq(images=[FRAME] * image_count, prompt="Q")

    if delivered:
        provider.describe(request)

        assert fake_urlopen.call_count == 1
    else:
        with pytest.raises(ImageNotDelivered) as exc_info:
            provider.describe(request)

        assert exc_info.value.floor == IMAGE_TOKEN_FLOOR * image_count


def test_the_floor_scales_with_images_actually_sent_not_the_input_count(
    monkeypatch: pytest.MonkeyPatch, fake_urlopen: FakeUrlopen
) -> None:
    """Qwen 4 张图、报回 100 → 抛：单张的门槛放过它，四张不放，floor 为 400。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    provider = QwenProvider(temperature=0.0)
    with_prompt_tokens(fake_urlopen, 100)
    request = VisionDescribeReq(images=[FRAME] * 4, prompt="Q")

    with pytest.raises(ImageNotDelivered) as exc_info:
        provider.describe(request)

    assert exc_info.value.floor == 400
    assert exc_info.value.input_tokens == 100


@pytest.mark.parametrize("prompt_tokens", [99, 100])
def test_arks_floor_stays_at_one_image_no_matter_the_input_count(
    prompt_tokens: int, monkeypatch: pytest.MonkeyPatch, fake_urlopen: FakeUrlopen
) -> None:
    """Ark 永远发 1 张网格图，门槛不随输入张数放大：4 张输入报回 99 抛、100 过。"""

    monkeypatch.setenv("ARK_API_KEY", "sk-a")
    provider = ArkProvider("doubao-x", temperature=0.0)
    with_prompt_tokens(fake_urlopen, prompt_tokens)
    # Ark 会解码多帧拼网格，占位帧过不了解码，用真帧。
    real_frames = [solid_frame((255, 0, 0)) for _ in range(4)]
    request = VisionDescribeReq(images=real_frames, prompt="Q")

    if prompt_tokens == 99:
        with pytest.raises(ImageNotDelivered) as exc_info:
            provider.describe(request)

        assert exc_info.value.floor == 100
    else:
        provider.describe(request)

        assert fake_urlopen.call_count == 1


@pytest.mark.parametrize(
    ("prompt_tokens", "delivered"), [(50, True), (49, False)], ids=["at-floor", "below-floor"]
)
def test_a_custom_token_floor_moves_the_boundary(
    prompt_tokens: int,
    delivered: bool,
    monkeypatch: pytest.MonkeyPatch,
    fake_urlopen: FakeUrlopen,
) -> None:
    """token_floor=50 时报回 50 通过、49 抛。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    provider = QwenProvider(temperature=0.0, token_floor=50)
    with_prompt_tokens(fake_urlopen, prompt_tokens)

    if delivered:
        provider.describe(VisionDescribeReq(images=[FRAME], prompt="Q"))

        assert fake_urlopen.call_count == 1
    else:
        with pytest.raises(ImageNotDelivered):
            provider.describe(VisionDescribeReq(images=[FRAME], prompt="Q"))


def test_the_default_token_floor_equals_image_token_floor(
    monkeypatch: pytest.MonkeyPatch, fake_urlopen: FakeUrlopen
) -> None:
    """缺省门槛等于 IMAGE_TOKEN_FLOOR：1 张图报回它减一就抛（不读私有属性来观察）。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    provider = QwenProvider(temperature=0.0)
    with_prompt_tokens(fake_urlopen, IMAGE_TOKEN_FLOOR - 1)

    with pytest.raises(ImageNotDelivered) as exc_info:
        provider.describe(VisionDescribeReq(images=[FRAME], prompt="Q"))

    assert exc_info.value.floor == IMAGE_TOKEN_FLOOR


def test_image_not_delivered_carries_the_counters_and_names_the_silence(
    monkeypatch: pytest.MonkeyPatch, fake_urlopen: FakeUrlopen
) -> None:
    """ImageNotDelivered 的 input_tokens/floor 等于观察值，消息含 silently dropped。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    provider = QwenProvider(temperature=0.0)
    with_prompt_tokens(fake_urlopen, 42)
    request = VisionDescribeReq(images=[FRAME] * 3, prompt="Q")

    with pytest.raises(ImageNotDelivered) as exc_info:
        provider.describe(request)

    assert exc_info.value.input_tokens == 42
    assert exc_info.value.floor == 300
    assert "silently dropped" in str(exc_info.value)
