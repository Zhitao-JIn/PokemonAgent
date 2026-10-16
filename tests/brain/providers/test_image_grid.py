"""网格拼图契约：``image_grid_dims`` 的行列数、``pack_images_grid`` 的版面与 Ark 的单图保证。"""

from __future__ import annotations

import base64
import io

import pytest
from _doubles.frames import solid_frame
from PIL import Image

from pokemon_agent.brain.providers import (
    ArkProvider,
    DeepSeekProvider,
    QwenProvider,
    image_grid_dims,
    pack_images_grid,
)
from pokemon_agent.brain.schemas import VisionDescribeReq

KEY_VARS = ("DASHSCOPE_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ARK_API_KEY", "DEEPSEEK_API_KEY")

RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
YELLOW = (255, 255, 0)
BLACK = (0, 0, 0)


def uri_to_image(uri: str) -> Image.Image:
    """把 PNG data URI 解码回 PIL 图像，供像素断言用。"""

    payload = uri.split(",", 1)[1]
    return Image.open(io.BytesIO(base64.b64decode(payload)))


@pytest.fixture(autouse=True)
def _no_keys_in_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """每个测试先把四个 key 变量全清掉，不依赖机器上的真实环境。"""

    for name in KEY_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    ("count", "expected_dims"),
    [
        (1, (1, 3)),
        (2, (1, 3)),
        (3, (1, 3)),
        (4, (2, 3)),
        (5, (2, 3)),
        (6, (2, 3)),
        (7, (3, 3)),
    ],
)
def test_the_grid_is_three_columns_with_rows_as_needed(
    count: int, expected_dims: tuple[int, int]
) -> None:
    """列数固定 3，行数 ceil(n/3)：n=1..7 的行列数。"""

    assert image_grid_dims(count) == expected_dims


def test_an_empty_grid_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """空列表直接 AssertionError。"""

    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    with pytest.raises(AssertionError, match="got no images"):
        pack_images_grid([])


def test_a_single_frame_is_returned_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    """单张输入返回的就是这一帧本身（同一字符串），不重新编码。"""

    frame = solid_frame(RED)

    assert pack_images_grid([frame]) is frame


def test_a_grid_with_a_non_data_uri_frame_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """拼接路径上出现非 data URI 的帧 → AssertionError（用 2 张触发拼接）。"""

    frame = solid_frame(RED)

    with pytest.raises(AssertionError, match="帧不是 data URI 格式"):
        pack_images_grid([frame, "not-a-uri"])


@pytest.mark.parametrize(
    ("count", "expected_size"),
    [(4, (488, 292)), (2, (488, 144)), (3, (488, 144)), (7, (488, 440))],
)
def test_the_canvas_grows_by_rows_while_staying_three_columns_wide(
    count: int, expected_size: tuple[int, int]
) -> None:
    """4 张 → 488×292；2、3 张 → 488×144（不足 3 张右边留黑）；7 张 → 488×440。"""

    frames = [solid_frame(RED) for _ in range(count)]

    packed = uri_to_image(pack_images_grid(frames))

    assert packed.size == expected_size


def test_the_packed_grid_is_a_decodable_png_data_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    """返回值是 `data:image/png;base64,` 开头、可解码的 PNG。"""

    packed = pack_images_grid([solid_frame(RED), solid_frame(GREEN)])

    assert packed.startswith("data:image/png;base64,")

    uri_to_image(packed)  # 解码失败会抛


def test_frames_sit_row_first_with_black_separators_and_empty_cells(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """4 张纯色帧行优先摆放：中心像素依次落位，4 像素黑线分隔，空格子是黑。"""

    frames = [solid_frame(c) for c in (RED, GREEN, BLUE, YELLOW)]

    packed = uri_to_image(pack_images_grid(frames))

    assert packed.getpixel((10, 10)) == RED
    assert packed.getpixel((174, 10)) == GREEN
    assert packed.getpixel((338, 10)) == BLUE
    assert packed.getpixel((10, 158)) == YELLOW

    assert packed.getpixel((161, 10)) == BLACK
    assert packed.getpixel((10, 145)) == BLACK

    assert packed.getpixel((338, 158)) == BLACK
    assert packed.getpixel((418, 158)) == BLACK


def test_ark_describe_sends_exactly_one_grid_image_for_multiple_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ark 多张输入 → 请求体恰好 1 个 image_url，解码尺寸等于 pack_images_grid 的结果。"""

    monkeypatch.setenv("ARK_API_KEY", "sk-a")
    import urllib.request

    from _doubles.http import FakeUrlopen

    fake = FakeUrlopen()
    fake.next_body = {
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 1},
    }
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    ark = ArkProvider("doubao-x", temperature=0.0)
    frames = [solid_frame(c) for c in (RED, GREEN, BLUE, YELLOW)]

    ark.describe(VisionDescribeReq(images=frames, prompt="Q"))
    content = fake.calls[0]["json"]["messages"][0]["content"]
    image_blocks = [block for block in content if block["type"] == "image_url"]

    assert len(image_blocks) == 1
    grid_uri = image_blocks[0]["image_url"]["url"]

    assert grid_uri not in frames
    assert uri_to_image(grid_uri).size == uri_to_image(pack_images_grid(frames)).size


def test_ark_describe_passes_a_single_frame_through_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ark 单张输入 → 原样透传，不重新编码。"""

    monkeypatch.setenv("ARK_API_KEY", "sk-a")
    import urllib.request

    from _doubles.http import FakeUrlopen

    fake = FakeUrlopen()
    fake.next_body = {
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 1},
    }
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    ark = ArkProvider("doubao-x", temperature=0.0)
    frame = solid_frame(RED)

    ark.describe(VisionDescribeReq(images=[frame], prompt="Q"))
    content = fake.calls[0]["json"]["messages"][0]["content"]

    assert content[1]["image_url"]["url"] == frame


def test_ark_describe_rejects_a_mixed_non_data_uri_frame_before_sending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ark 多帧里混入非 data URI → AssertionError，替身调用次数 0。"""

    monkeypatch.setenv("ARK_API_KEY", "sk-a")
    import urllib.request

    from _doubles.http import FakeUrlopen

    fake = FakeUrlopen()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    ark = ArkProvider("doubao-x", temperature=0.0)

    with pytest.raises(AssertionError, match="帧不是 data URI 格式"):
        ark.describe(VisionDescribeReq(images=[solid_frame(RED), "not-a-uri"], prompt="Q"))

    assert fake.call_count == 0


@pytest.mark.parametrize("vendor_class", [QwenProvider, DeepSeekProvider])
def test_qwen_and_deepseek_do_not_pack_a_grid(
    vendor_class: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Qwen 与 DeepSeek 多张输入不拼网格：image_url 数量等于输入张数且 url 原样。"""

    env = "DASHSCOPE_API_KEY" if vendor_class is QwenProvider else "DEEPSEEK_API_KEY"
    monkeypatch.setenv(env, "sk-x")
    import urllib.request

    from _doubles.http import FakeUrlopen

    fake = FakeUrlopen()
    fake.next_body = {
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 1},
    }
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    frames = [solid_frame(c) for c in (RED, GREEN, BLUE)]
    provider = (
        vendor_class(temperature=0.0)
        if vendor_class is QwenProvider
        else vendor_class(temperature=0.0)
    )

    provider.describe(VisionDescribeReq(images=frames, prompt="Q"))
    content = fake.calls[0]["json"]["messages"][0]["content"]
    image_urls = [block["image_url"]["url"] for block in content if block["type"] == "image_url"]

    assert image_urls == frames


def test_pack_images_grid_lays_frames_out_at_their_own_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """帧按原尺寸贴进画布，不缩放——红绿两帧中心像素仍落在各自帧内。"""

    frames = [solid_frame(RED), solid_frame(GREEN)]

    packed = uri_to_image(pack_images_grid(frames))

    assert packed.getpixel((80, 72)) == RED
    assert packed.getpixel((244, 72)) == GREEN


def test_frames_of_different_sizes_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """帧尺寸不一致 → AssertionError（O17）：静默裁剪大的、留黑小的不如当场炸。"""

    frames = [solid_frame(RED, size=(160, 144)), solid_frame(GREEN, size=(200, 200))]

    with pytest.raises(AssertionError):
        pack_images_grid(frames)


def test_a_single_frame_also_passes_the_uri_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """单张非 data URI → AssertionError（O18）：不能因为不拼接就绕过校验。"""

    with pytest.raises(AssertionError, match="帧不是 data URI 格式"):
        pack_images_grid(["not-a-uri"])
