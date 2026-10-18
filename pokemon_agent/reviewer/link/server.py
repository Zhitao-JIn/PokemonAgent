"""单连接复核服务，按 qid 保留当前问与答复缓存，瞬时断线不重开问题。"""

import asyncio
import hashlib
import json
import logging
from collections import OrderedDict
from contextlib import suppress
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, ValidationError
from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed

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

from .ports import QuestionHandler

logger = logging.getLogger(__name__)
_Messages = Annotated[
    FromHarnessToReviewerAskMsg | FromHarnessToReviewerCancelMsg, Field(discriminator="msg")
]


@dataclass
class _Entry:
    signature: str
    answer: FromReviewerToHarnessAnswerMsg | None = None
    cancelled: bool = False


class ReviewLinkServer:
    """调用方将本服务、应用与终端放在同一事件循环；mode 显式来自装配。"""

    def __init__(self, app: QuestionHandler, *, mode: Literal["human", "ai", "both"]) -> None:
        self._app = app
        self._mode = mode
        self._connection: ServerConnection | None = None
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._active: str | None = None
        self._task: asyncio.Task[None] | None = None

    async def serve(self, host: str, port: int) -> Server:
        """监听地址被占时直接抛 OSError，不换端口；返回的 Server 由调用方关闭。"""
        return await serve(self.handle, host, port, max_size=None)

    async def handle(self, connection: ServerConnection) -> None:
        """第二个连接明确拒绝；非法线上信封以协议错误关闭，不能进入业务路径。"""
        if self._connection is not None:
            logger.warning("已有 run 占用 reviewer，拒绝第二个连接")
            await connection.close(1013, "已有 run 占用 reviewer")
            return
        self._connection = connection
        try:
            await connection.send(FromReviewerToHarnessHelloMsg(mode=self._mode).model_dump_json())
            async for raw in connection:
                try:
                    message = TypeAdapter(_Messages).validate_json(raw)
                except ValidationError:
                    await connection.close(1008, "非法 reviewer 信封")
                    return
                if isinstance(message, FromHarnessToReviewerCancelMsg):
                    await self._cancel(message.qid)
                elif not await self._ask(message, connection):
                    return
        except ConnectionClosed:
            logger.info("reviewer 连接中断，保留当前问等待原 qid 重发")
        finally:
            if self._connection is connection:
                self._connection = None

    async def _ask(self, wire: FromHarnessToReviewerAskMsg, connection: ServerConnection) -> bool:
        """同 qid 同素材重发不重复询问，答过即回缓存，qid 改素材拒绝。"""
        signature = hashlib.sha256(
            json.dumps(wire.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()
        if wire.qid in self._entries:
            entry = self._entries[wire.qid]
            if entry.signature != signature or entry.cancelled:
                await connection.close(1008, "qid 已取消或素材不一致")
                return False
            if entry.answer is not None:
                await connection.send(entry.answer.model_dump_json())
            return True
        if self._active is not None:
            await connection.close(1008, "已有未答问题占用 reviewer")
            return False
        self._entries[wire.qid] = _Entry(signature)
        self._active = wire.qid
        self._task = asyncio.create_task(self._complete(wire))
        return True

    async def _complete(self, wire: FromHarnessToReviewerAskMsg) -> None:
        """答复先缓存再发送；发送失败时仍可在重连后取回。"""
        entry = self._entries[wire.qid]
        try:
            result = await self._app.ask(wire.req)
            if result.cancelled:
                entry.cancelled = True
            else:
                assert result.response is not None
                entry.answer = FromReviewerToHarnessAnswerMsg(qid=wire.qid, resp=result.response)
        except asyncio.CancelledError:
            entry.cancelled = True
            raise
        except Exception:
            entry.cancelled = True
            logger.exception("reviewer 应用异常，当前问已取消")
            if self._connection is not None:
                await self._connection.close(1011, "reviewer 应用异常")
            raise
        finally:
            if self._active == wire.qid:
                self._active = None
        if self._connection is not None:
            if entry.answer is not None:
                with suppress(ConnectionClosed):
                    await self._connection.send(entry.answer.model_dump_json())
            else:
                await self._connection.close(1008, "该问已取消")

    async def _cancel(self, qid: str) -> None:
        """取消仅影响该 qid；等待应用的 finally 解除 pending 后再接下一问。"""
        entry = self._entries.get(qid)
        if entry is None or entry.answer is not None or entry.cancelled:
            return
        entry.cancelled = True
        if self._active == qid and self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._active = None

    async def shutdown(self) -> None:
        """服务退出取消当前问；瞬时断开 handle 不执行此操作。"""
        if self._active is not None:
            await self._cancel(self._active)
        if self._task is not None and self._task.done():
            with suppress(asyncio.CancelledError):
                await self._task
