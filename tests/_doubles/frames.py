"""按颜色与尺寸造一帧纯色 PNG data URI，供多模态/网格测试当帧用。"""

from __future__ import annotations

import base64
import io

from PIL import Image


def solid_frame(color: tuple[int, int, int], size: tuple[int, int] = (160, 144)) -> str:
    """造一张纯色 PNG 并编码成 `data:image/png;base64,…`。"""

    image = Image.new("RGB", size, color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
