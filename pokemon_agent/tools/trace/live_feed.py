"""`LiveFeedTrace`：`TracePort` 的装饰器——每落一笔账，顺手把同一条事件推给人在环后端。

**盘上的账是唯一真相，这一路只供网页实时看**（`docs/web_reviewer/spec.md` §6.4）：
`append` 先照常落盘，再把事件丢进有界队列就返回；后台 daemon 线程连后端 `/feed` 发送。
队列满了丢最旧的；后端不在或断了就丢弃，每隔几秒重试一次连接，状态变化时各打一行日志。
它不会让 run 变慢，也不会让 run 失败。
"""

from __future__ import annotations

import contextlib
import json
import queue
import threading
import time
from typing import Any

from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI
from websockets.sync.client import ClientConnection, connect

from pokemon_agent.schemas.harness import FromHarnessToReviewBackendFeedReq, TraceEvent
from pokemon_agent.trace import Event, TracePort

QUEUE_LIMIT = 1000
"""待发事件的上限；满了丢最旧的。"""

RETRY_S = 5.0
"""后端不在时，隔多久再试一次连接。"""

CONNECT_TIMEOUT_S = 3.0
"""连后端 `/feed` 的等待上限。"""


class LiveFeedTrace:
    """包在落盘实现外面：写照写、读照读，另外把写出的每条事件异步推给后端。"""

    def __init__(self, inner: TracePort, *, run_id: str, branch: str, url: str) -> None:
        """接好落盘实现与后端地址，起后台发送线程。

        inner：真正落盘的 `TracePort`。
        run_id / branch：落盘层会盖进 `meta` 的两件，推送的事件照样盖上（与盘上同形）。
        url：后端地址（`ws://host:port`），事件发往 `url + "/feed"`。
        """
        self._inner, self._run_id, self._branch, self._url = inner, run_id, branch, url
        self._queue: queue.Queue[FromHarnessToReviewBackendFeedReq] = queue.Queue(QUEUE_LIMIT)
        threading.Thread(target=self._pump, name="live-feed", daemon=True).start()

    def append(
        self,
        type: str,
        kind: str,
        meta: dict[str, Any] | None = None,
        content: Any = None,  # noqa: ANN401 —— 账的本体就是任意可 JSON 化的对象
    ) -> str:
        """先落盘（契约同 `TracePort.append`），再把同一条事件放进待发队列。"""
        event_uuid = self._inner.append(type, kind, meta, content)
        event = TraceEvent(
            uuid=event_uuid,
            kind=kind,
            type=type,
            ts=time.time(),
            meta=json.dumps(
                {**(meta or {}), "run_id": self._run_id, "branch": self._branch},
                ensure_ascii=False,
            ),
            content=json.dumps(content, ensure_ascii=False),
        )
        self._offer(FromHarnessToReviewBackendFeedReq(run_id=self._run_id, event=event))
        return event_uuid

    def read_events(self, meta: dict[str, Any] | None = None) -> list[Event]:
        """原样转给落盘实现。"""
        return self._inner.read_events(meta)

    def _offer(self, item: FromHarnessToReviewBackendFeedReq) -> None:
        """入队；满了先丢最旧的一条。"""
        while True:
            try:
                self._queue.put_nowait(item)
                return
            except queue.Full:
                with contextlib.suppress(queue.Empty):
                    self._queue.get_nowait()

    def _pump(self) -> None:
        """后台线程：连上就逐条发；连不上或断了就丢弃当前这条，隔 `RETRY_S` 再连。"""
        conn: ClientConnection | None = None
        next_try = 0.0
        while True:
            item = self._queue.get()
            if conn is None and time.monotonic() >= next_try:
                conn = self._connect()
                next_try = time.monotonic() + RETRY_S
            if conn is None:
                continue
            try:
                conn.send(item.model_dump_json())
            except (ConnectionClosed, OSError):
                _say("后端断开，实时画面暂停推送（run 不受影响）")
                conn = None
                next_try = time.monotonic() + RETRY_S

    def _connect(self) -> ClientConnection | None:
        """连后端 `/feed`（不走代理）；连不上返回 None。"""
        try:
            conn = connect(f"{self._url}/feed", proxy=None, open_timeout=CONNECT_TIMEOUT_S)
        except (OSError, TimeoutError, InvalidHandshake, InvalidURI):
            return None
        _say(f"实时画面开始推送到 {self._url}")
        return conn


def _say(line: str) -> None:
    """推送动态一行一条打到 stdout（带 flush）。"""
    print(f"[feed] {line}", flush=True)


__all__ = ["LiveFeedTrace"]
