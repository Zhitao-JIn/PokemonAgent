"""帧编码：原始 PNG 字节 → 完整 data URI（全仓唯一的帧编码点）。"""

from __future__ import annotations

import base64

from pokemon_agent.world.frame_encoding import png_data_uri

PREFIX = "data:image/png;base64,"


def test_png_data_uri_prefix_and_base64() -> None:
    raw = b"\x89PNG\r\n"

    uri = png_data_uri(raw)

    assert uri.startswith(PREFIX)
    assert base64.b64decode(uri[len(PREFIX) :]) == raw


def test_empty_png_still_prefixed() -> None:
    assert png_data_uri(b"") == PREFIX
