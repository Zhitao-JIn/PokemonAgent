"""帧槽：`_tick` 每帧塞最新画面（生产者），SSE 端按自己的节奏取（消费者）。

**单槽覆盖 + 惰性编码**——生产者每 tick 只换图像引用（O(1)，不编码），
PNG 编码只在消费者取帧那一刻发生，并缓存到下一次 `push`。这样既满足
"每一帧都推进槽"（语义上永远是最新帧），又没有"每帧编码 PNG"的成本：
无头模式（`speed=0`）不限速，模拟器可能几百帧/秒，每帧编码会把整个
run 拖慢——而消费者（前端）根本消费不了那么高的帧率。

线程安全：run 线程 `push`，API 的 SSE 线程 `latest()`。
"""

from __future__ import annotations

import io
import threading

from PIL import Image


class FrameSlot:
    """最新一帧的槽。生产者覆盖，消费者取走即最新，取不到返回 `None`。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._image: Image.Image | None = None
        self._encoded: bytes | None = None

    def push(self, image: Image.Image) -> None:
        """塞进最新一帧（O(1)：只换引用，不做任何编码）。

        调用方负责传入**这一帧独有的副本**（PyBoy 的 `screen.image` 是
        `frombuffer` 共享渲染缓冲的视图，下一帧 tick 会覆盖底层数据，
        所以必须 `copy()` 过再塞进来）。
        """
        with self._lock:
            self._image = image
            self._encoded = None  # 缓存失效——取帧时重新编码

    def latest(self) -> bytes | None:
        """取最新一帧的 PNG 字节；还没有任何帧时返回 `None`。

        编码只发生在这里，且同一帧只编一次（`push` 后缓存失效）。
        """
        with self._lock:
            image = self._image
            if image is None:
                return None
            if self._encoded is None:
                buf = io.BytesIO()
                image.save(buf, format="PNG")
                self._encoded = buf.getvalue()
            return self._encoded
