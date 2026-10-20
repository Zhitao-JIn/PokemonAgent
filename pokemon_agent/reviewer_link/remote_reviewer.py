"""同步 Reviewer 适配：后台 WS 线程重连，图线程只等一次 Future。"""

import asyncio
import logging
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future
from contextlib import suppress
from urllib.parse import urlsplit

from pydantic import ValidationError
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from pokemon_agent.schemas.harness import (
    FromHarnessToReviewerAuditReq,
    FromHarnessToReviewerAuditResp,
    FromHarnessToReviewerInjectReq,
    FromHarnessToReviewerInjectResp,
)
from pokemon_agent.schemas.harness.communication.FromHarnessToReviewerAskMsg import (
    FromHarnessToReviewerAskMsg,
)
from pokemon_agent.schemas.harness.communication.FromHarnessToReviewerCancelMsg import (
    FromHarnessToReviewerCancelMsg,
)
from pokemon_agent.schemas.reviewer.communication import (
    FromReviewerToHarnessAnswerMsg,
    FromReviewerToHarnessHelloMsg,
)
from pokemon_agent.schemas.reviewer.interaction import ReviewRequest, ReviewResponse

from .protocol import Pending, ReviewerProtocolError, default_response, matching_response

logger = logging.getLogger(__name__)
_CONNECT_TIMEOUT_S = 3.0
_WARNING_INTERVAL_S = 30.0
_MONITOR_INTERVAL_S = 0.1


class RemoteReviewer:
    """一实例最多一问；lost_timeout_s 由装配点传 config 值，None 禁止 AI 断线降级。"""

    def __init__(
        self, url: str, *, flush: Callable[[], None], lost_timeout_s: float | None
    ) -> None:
        parsed = urlsplit(url)
        if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
            raise ValueError("reviewer URL 必须是 ws:// 或 wss:// 地址")
        if parsed.port == 0:
            raise ValueError("客户端需要 reviewer 实际监听端口，不能连接端口 0")
        if lost_timeout_s is not None and lost_timeout_s < 0:
            raise ValueError("断线预算不能为负数")
        self._url, self._flush, self._timeout = url, flush, lost_timeout_s
        self._lock = threading.RLock()
        self._ready = threading.Event()
        self._closed = False
        self._fatal: BaseException | None = None
        self._pending: Pending | None = None
        self._cancel_qids: list[str] = []
        self._mode: str | None = None
        self._lost_since: float | None = time.monotonic()
        self._last_warning = 0.0
        self._socket: ClientConnection | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._timer: asyncio.TimerHandle | None = None
        self._send_lock: asyncio.Lock | None = None
        self._thread = threading.Thread(target=self._run, daemon=True, name="reviewer-link")
        self._thread.start()
        self._ready.wait()

    def inject(self, req: FromHarnessToReviewerInjectReq) -> FromHarnessToReviewerInjectResp:
        """提问前同步 flush；人或未知模式断线时持续等待，明确关闭才返回默认值。"""
        response = self._exchange(req, "inject")
        assert isinstance(response, FromHarnessToReviewerInjectResp)
        return response

    def audit(self, req: FromHarnessToReviewerAuditReq) -> FromHarnessToReviewerAuditResp:
        """提问前 flush，审问与插话共享同一条后台连接及席位模式。"""
        response = self._exchange(req, "audit")
        assert isinstance(response, FromHarnessToReviewerAuditResp)
        return response

    def _exchange(self, req: ReviewRequest, op: str) -> ReviewResponse:
        """只允许一个同步调用在途，原请求序列化后在重发期间保持不变。"""
        self._flush()
        with self._lock:
            if self._fatal is not None:
                raise RuntimeError("reviewer 后台线程异常退出") from self._fatal
            if self._closed:
                return default_response(op)
            assert self._pending is None, "only one reviewer request may be in flight"
            wire = FromHarnessToReviewerAskMsg(
                qid=str(uuid.uuid4()), op=op, req=req.model_copy(deep=True)
            )
            pending = Pending(wire, Future())
            self._pending = pending
            self._last_warning = 0
        assert self._loop is not None
        asyncio.run_coroutine_threadsafe(self._send(), self._loop)
        try:
            return pending.future.result()
        except BaseException:
            self._abandon(pending)
            raise

    def _abandon(self, pending: Pending) -> None:
        """调用方异常退出后取消原 qid；断线时留待重连再发，不取消下一问。"""
        with self._lock:
            if self._pending is not pending:
                return
            self._pending = None
            self._cancel_qids.append(pending.wire.qid)
            pending.future.cancel()
        if self._loop is not None and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._send(), self._loop)

    def _run(self) -> None:
        """后台线程只运行一个事件循环；异常传播给同步调用方，不伪装成无人答复。"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._stop = asyncio.Event()
        self._send_lock = asyncio.Lock()
        self._ready.set()
        try:
            self._loop.run_until_complete(self._serve())
        except BaseException as exc:
            with self._lock:
                self._fatal = exc
                if self._pending is not None:
                    self._pending.future.set_exception(exc)
                    self._pending = None
            logger.exception("reviewer 后台线程退出")
        finally:
            self._loop.close()

    async def _serve(self) -> None:
        """连接由 websockets 的异步重连迭代器管理，关闭取消连接任务与监视器。"""
        assert self._stop is not None
        runner = asyncio.create_task(self._connections())
        stopping = asyncio.create_task(self._stop.wait())
        self._monitor()
        try:
            done, _ = await asyncio.wait({runner, stopping}, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            runner.cancel()
            stopping.cancel()
            for task in (runner, stopping):
                with suppress(asyncio.CancelledError):
                    await task
            if self._timer is not None:
                self._timer.cancel()

    async def _connections(self) -> None:
        """重连后先确认 hello，再发积压取消与原 qid；从不因连不上推测 AI 模式。"""
        async for socket in connect(
            self._url,
            proxy=None,
            open_timeout=_CONNECT_TIMEOUT_S,
            max_size=None,
            process_exception=lambda error: None,
        ):
            try:
                raw = await asyncio.wait_for(socket.recv(), _CONNECT_TIMEOUT_S)
                hello = FromReviewerToHarnessHelloMsg.model_validate_json(raw)
                with self._lock:
                    self._mode, self._socket, self._lost_since = hello.mode, socket, None
                await self._send()
                async for raw in socket:
                    self._receive(raw)
            except (
                ConnectionClosed,
                OSError,
                TimeoutError,
                ValidationError,
                ReviewerProtocolError,
            ) as exc:
                logger.debug("reviewer 链路中断：%s", type(exc).__name__)
            finally:
                with self._lock:
                    self._socket = None
                    if self._lost_since is None:
                        self._lost_since = time.monotonic()
                await socket.close()
            await asyncio.sleep(_MONITOR_INTERVAL_S)

    def _receive(self, raw: str | bytes) -> None:
        """迟到的其他 qid 不能解锁当前问，相同 qid 的操作类型也必须匹配。"""
        message = FromReviewerToHarnessAnswerMsg.model_validate_json(raw)
        with self._lock:
            if self._pending is None or message.qid != self._pending.wire.qid:
                return
            response = matching_response(self._pending, message)
            self._pending.future.set_result(response)
            self._pending = None

    async def _send(self) -> None:
        """发送时再次取锁内快照；断线只保留原问，重连负责重发。"""
        assert self._send_lock is not None
        async with self._send_lock:
            await self._send_locked()

    async def _send_locked(self) -> None:
        """取消与提问串行发送，防止取消先发而迟到的原问又占住服务端。"""
        with self._lock:
            socket, pending, cancels = self._socket, self._pending, list(self._cancel_qids)
        if socket is None:
            return
        try:
            for qid in cancels:
                await socket.send(FromHarnessToReviewerCancelMsg(qid=qid).model_dump_json())
                with self._lock:
                    if qid in self._cancel_qids:
                        self._cancel_qids.remove(qid)
            if pending is not None:
                await socket.send(pending.wire.model_dump_json())
        except ConnectionClosed:
            logger.info("reviewer 发送时断线，等待重连")

    def _monitor(self) -> None:
        """固定节拍只监视断线预算；human/both/未知模式绝不按时间放行。"""
        with self._lock:
            now, lost, pending = time.monotonic(), self._lost_since, self._pending
            if not self._closed and pending is not None and lost is not None:
                if now - self._last_warning >= _WARNING_INTERVAL_S:
                    logger.warning("reviewer 未连接，正在等待重连（mode=%s）", self._mode or "未知")
                    self._last_warning = now
                if self._mode == "ai" and self._timeout is not None and now - lost >= self._timeout:
                    logger.warning("AI reviewer 断线预算耗尽，本问按无人作答处理")
                    self._cancel_qids.append(pending.wire.qid)
                    pending.future.set_result(default_response(pending.wire.op))
                    self._pending = None
            if not self._closed:
                assert self._loop is not None
                self._timer = self._loop.call_later(_MONITOR_INTERVAL_S, self._monitor)

    def close(self) -> None:
        """幂等关闭并唤醒同步等待方；能连接时先发送 cancel，再停止后台线程。"""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._pending is not None:
                self._cancel_qids.append(self._pending.wire.qid)
                self._pending.future.set_result(default_response(self._pending.wire.op))
                self._pending = None
        if self._loop is not None and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
            future.result(timeout=_CONNECT_TIMEOUT_S + 1)
        self._thread.join(timeout=_CONNECT_TIMEOUT_S + 1)

    async def _shutdown(self) -> None:
        """退出取消不会重发刚放弃的 ask；无连接时取消只能尽力而为。"""
        await self._send()
        if self._socket is not None:
            await self._socket.close()
        assert self._stop is not None
        self._stop.set()
