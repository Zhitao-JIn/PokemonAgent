"""手写的 ``urllib.request.urlopen`` 替身：记录每次请求、按脚本回话或抛错。

供 ``tests/brain/providers/`` 各测试文件经 ``monkeypatch`` 装到
``"urllib.request.urlopen"`` 上使用；不用 ``unittest.mock``。
"""

from __future__ import annotations

import io
import json
import threading
from typing import Any
from urllib.error import HTTPError


def ok_body(
    *,
    text: str | None = "hi",
    finish: str | None = "stop",
    prompt_tokens: int = 11,
    completion_tokens: int = 5,
    cached_tokens: int = 3,
    reasoning_tokens: int = 2,
) -> dict:
    """造一个 OpenAI 兼容的完整响应体；``finish=None`` 时省略该字段。"""

    choice: dict = {"message": {"content": text}}
    if finish is not None:
        choice["finish_reason"] = finish
    return {
        "choices": [choice],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "prompt_tokens_details": {"cached_tokens": cached_tokens},
            "completion_tokens_details": {"reasoning_tokens": reasoning_tokens},
        },
    }


class _FakeResponse:
    """最小的读一次就完的响应对象，支持 ``with`` 语法。"""

    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> bytes:
        return self._text.encode()

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False


class FakeUrlopen:
    """记录每次调用的 urlopen 替身：URL、小写键请求头、JSON 体、timeout。"""

    def __init__(self, *, body: dict | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.next_body: dict = body if body is not None else ok_body()
        self.next_exc: Exception | None = None

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def __call__(self, req: Any, timeout: float | None = None) -> _FakeResponse:
        raw = req.data.decode() if req.data else ""
        self.calls.append(
            {
                "url": req.full_url,
                "headers": {k.lower(): v for k, v in req.header_items()},
                "json": json.loads(raw) if raw else None,
                "timeout": timeout,
            }
        )
        if self.next_exc is not None:
            exc, self.next_exc = self.next_exc, None
            raise exc
        return _FakeResponse(json.dumps(self.next_body))

    def http_error(self, code: int, body: str = "upstream said no") -> None:
        """让下一次调用抛带状态码与响应体的 ``HTTPError``。"""

        self.next_exc = HTTPError("url", code, "reason", None, io.BytesIO(body.encode()))


class BlockingUrlopen:
    """阻塞在 ``threading.Event`` 上的替身：测单请求总时长硬闸专用。

    使用方必须在 ``finally`` 里 ``release.set()``，否则工作线程永远挂着。
    """

    def __init__(self) -> None:
        self.release = threading.Event()
        self.calls = 0

    def __call__(self, req: Any, timeout: float | None = None) -> _FakeResponse:
        self.calls += 1
        self.release.wait()
        return _FakeResponse("{}")
