"""视觉子节点：截图与 prompt → 原始视觉字段及一次调用账，不读 RAM。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .errors import PerceptionAttemptFailed
from .frame_encoding import png_data_uri
from .interface import ScreenState, VisionDescribeReq, VisionProvider


class VisualRead(BaseModel):
    """纯视觉结果；调用方可以再与机械观测组装，测评直接判这份结果。"""

    screen: ScreenState
    call: dict[str, Any]


def parse_screen(text: str) -> ScreenState | None:
    """把视觉模型的输出解析成 `ScreenState`。

    容忍 ```json 包裹——模型最常见的格式偏差，为它多跑一轮不划算。
    其余一律不兜底：解析不出来就是解析不出来，交给调用方重试。

    把视觉模型吐的 JSON 解析成 `ScreenState`。
    """
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```")[1].removeprefix("json").strip()
    try:
        return ScreenState.model_validate_json(t)
    except ValueError:  # ValidationError / JSONDecodeError 都是它的子类
        # 解析失败是预期内情况（模型输出格式问题），由调用方重试；
        # 只捕 ValueError 家族，预期外异常（bug）照常上抛。
        return None


def perceive_visual(png: bytes, *, prompt: str, vision: VisionProvider) -> VisualRead:
    """只问一次视觉模型。调用失败或解析失败带账抛 PerceptionAttemptFailed。"""
    try:
        r = vision.describe(VisionDescribeReq(images=[png_data_uri(png)], prompt=prompt))
    except PerceptionAttemptFailed:
        raise
    except Exception as exc:  # noqa: BLE001  上游网关/实现的任何失败都是"这次没读出来"
        raise PerceptionAttemptFailed(
            {
                "ok": "false",
                "raw": "",
                "prompt": prompt,
                "images": [png_data_uri(png)],
                "error": f"{type(exc).__name__}: {exc}",
            }
        ) from exc

    screen = parse_screen(r.text)
    call = {
        "input_tokens": str(r.input_tokens),
        "output_tokens": str(r.output_tokens),
        "cached_tokens": str(r.cached_tokens),
        "reasoning_tokens": str(r.reasoning_tokens),
        "ok": str(screen is not None).lower(),
        "raw": r.text,
        "prompt": prompt,
        "images": [png_data_uri(png)],
    }
    if screen is None:
        raise PerceptionAttemptFailed(call)

    return VisualRead(screen=screen, call=call)
