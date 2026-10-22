"""查询文本去图与事件行渲染；不依赖 harness 的展示实现。"""

import base64
import binascii
import json
import re
from datetime import datetime
from typing import Any

from pokemon_agent.schemas.harness import TraceEvent

_DATA_URI = re.compile(r"data:[^,\s\"'<>]*,[^\s\"'<>\\]*", re.IGNORECASE)
_FRAME_KEYS = frozenset(
    {
        "frame",
        "frame_png",
        "before_frame",
        "after_frame",
        "first_frame",
        "last_frame",
        "images",
        "frames",
    }
)


def text_without_frames(value: Any) -> str:  # noqa: ANN401
    """递归去掉帧字段和任意嵌入 data URI；在截断前执行，避免留下半条图片编码。"""
    clean = _without_frames(value)
    text = clean if isinstance(clean, str) else json.dumps(clean, ensure_ascii=False)
    return _DATA_URI.sub("[frame omitted]", text)


def _without_frames(value: Any) -> Any:  # noqa: ANN401
    """清理 JSON 形状内任意深度的图片素材，保留其余字段。"""
    if isinstance(value, dict):
        return {
            key: "[frame omitted]" if key in _FRAME_KEYS else _without_frames(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_without_frames(item) for item in value]
    if isinstance(value, str):
        return _DATA_URI.sub("[frame omitted]", value)
    return value


def event_line(event: TraceEvent, content_limit: int) -> str:
    """沿用时刻 · kind · source · step · content 格式；正文先去图再按查询上限截断。"""
    try:
        meta = json.loads(event.meta)
    except json.JSONDecodeError:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    try:
        content = json.loads(event.content)
    except json.JSONDecodeError:
        content = event.content
    text = " ".join(text_without_frames(content).split())
    excerpt = text[:content_limit]
    if content_limit and len(text) > content_limit:
        excerpt += "…"
    clock = datetime.fromtimestamp(event.ended_at).strftime("%H:%M:%S")
    where = f"{meta.get('source', '-')} · {meta.get('step', '-')}"
    return text_without_frames(f"{clock} · {event.kind} · {where} · {excerpt}")


def image_uri(value: object) -> str | None:
    """只允许非空 base64 图片 data URI 进入 images；缺失或坏帧返回 None。"""
    if not isinstance(value, str) or not value.startswith("data:image/"):
        return None
    header, separator, encoded = value.partition(",")
    if not separator or not header.endswith(";base64"):
        return None
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return None
    return value if decoded else None
