"""只读截图与冻结 RAM，核对商店实心箭头位置，不调用被测文字解码器。"""

import base64
import io
import zlib

import numpy as np
from PIL import Image
from pydantic import BaseModel

from evals.data.frames.schemas import ScreenSample

SOLID_CORE: tuple[str, ...] = ("##...", "###..", "####.", "#####", "####.", "###..", "##...")
"""已核对 p-shop_menu 的实心箭头核心5×7像素；不要求字形在8×8格内同一垂直相位。"""


class CursorEvidence(BaseModel):
    """截图像素位置与 RAM 图块位置分开呈现；一致只证明箭头位置，不证明全文同步。"""

    image: list[tuple[int, int]]
    ram: list[tuple[int, int]]
    hollow: list[tuple[int, int]]
    mismatch: bool
    method: str = "截图实心箭头5×7核心精确匹配；RAM为0xED/0xEC图块位置；坐标从0起"


def image_arrows(frame_png: str) -> list[tuple[int, int]]:
    """只读取原图像素；识别实心横向箭头，不将滚动三角或空心箭头当当前光标。"""
    image = Image.open(io.BytesIO(base64.b64decode(frame_png.split(",", 1)[1])))
    if image.size != (160, 144):
        raise ValueError("光标证据需要原始160×144截图")
    pixels = np.asarray(image.convert("L")) < 128
    mask = np.array([[value == "#" for value in row] for row in SOLID_CORE])
    matches = np.all(
        np.lib.stride_tricks.sliding_window_view(pixels, mask.shape) == mask, axis=(-1, -2)
    )
    return sorted(
        {((int(y) + 3) // 8, (int(x) + 2) // 8) for y, x in zip(*np.where(matches), strict=True)}
    )


def cursor_evidence(sample: ScreenSample) -> CursorEvidence:
    """核对一个商店样本，不能据此从截图覆盖冻结 RAM 真值。"""
    raw = zlib.decompress(base64.b64decode(sample.wram))
    if len(raw) != 8192:
        raise ValueError(f"{sample.sample_id}: 冻结WRAM长度错误")
    tiles = raw[0x3A0:0x508]
    ram = [(index // 20, index % 20) for index, tile in enumerate(tiles) if tile == 0xED]
    hollow = [(index // 20, index % 20) for index, tile in enumerate(tiles) if tile == 0xEC]
    image = image_arrows(sample.frame_png)
    return CursorEvidence(image=image, ram=ram, hollow=hollow, mismatch=image != ram)
