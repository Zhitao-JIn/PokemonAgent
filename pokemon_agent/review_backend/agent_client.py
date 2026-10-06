"""`AgentClient`：后端到 agent 进程（跳 C）的 WebSocket 客户端封装。

后端是 WS 客户端、agent 是 WS 服务端。后端与 agent 之间**只有一条长连接**：
seed/turn/close 都发在同一条连接上，agent 推回的 `proposal` 由本类的后台监听协程收到后交给后端广播。

**连不上不崩**：构造可传 `url=None`；`connect()` 失败（.env 缺失 / 地址错 / agent 没起）返回 False，
调用方据其降级为无 agent，run 照跑。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable

from websockets.asyncio.client import connect as _connect

from pokemon_agent.schemas.agent_reviewer.communication import (
    MSG_PROPOSAL,
    CloseReq,
    ProposalMsg,
    SeedReq,
    TurnReq,
)
from pokemon_agent.schemas.agent_reviewer.communication.ChatTurn import ChatTurn
from pokemon_agent.schemas.review_backend.communication.FromReviewBackendToFrontendAskReq import (
    FromReviewBackendToFrontendAskReq,
)

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT_S = 5.0
"""构造时连 agent 的等待上限。"""


class AgentClient:
    """后端侧跳 C 客户端：发 seed/turn/close，收 proposal。"""

    def __init__(self, url: str | None) -> None:
        self._url = url
        self._ws = None
        self._task: asyncio.Task | None = None
        self._on_proposal = None
        self.connected = False

    async def connect(self, on_proposal: Callable[[ProposalMsg], None]) -> bool:
        """连 agent；成功返回 True 并起监听协程，失败（无 url / 连不上）返回 False。"""
        if not self._url:
            return False
        try:
            self._ws = await _connect(self._url, proxy=None, open_timeout=CONNECT_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001  连不上 = 降级，不崩
            logger.warning("[agent] 连不上 %s，降级为无 agent：%s", self._url, exc)
            self._ws = None
            return False
        self.connected = True
        self._on_proposal = on_proposal
        self._task = asyncio.ensure_future(self._listen())
        return True

    async def _listen(self) -> None:
        """后台协程：收 agent 推回的 proposal，交给后端回调广播。连接断 = agent 崩。"""
        assert self._ws is not None
        try:
            async for raw in self._ws:
                try:
                    data = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                if data.get("msg") == MSG_PROPOSAL:
                    pm = ProposalMsg.model_validate(data)
                    if self._on_proposal is not None:
                        self._on_proposal(pm)
        except Exception:  # noqa: BLE001  连接断 / 解析错：本 seq 之后无提案，不重连
            self.connected = False
            self._ws = None

    async def seed(
        self, seq: int, ask: FromReviewBackendToFrontendAskReq, frame: str | None
    ) -> None:
        """开一问：把 pending 的那封 ask 与一帧发给 agent（不阻塞）。"""
        if not self.connected or self._ws is None:
            return
        req = SeedReq(seq=seq, ask=ask, frame=frame)
        try:
            await self._ws.send(req.model_dump_json())
        except Exception as exc:  # noqa: BLE001  发送失败：本问无提案
            logger.warning("[agent] seed 发送失败：%s", exc)

    async def turn(self, seq: int, delta: ChatTurn, frame: str | None) -> None:
        """增量：把人改稿发给 agent（不阻塞）。"""
        if not self.connected or self._ws is None:
            return
        req = TurnReq(seq=seq, delta=delta, frame=frame)
        try:
            await self._ws.send(req.model_dump_json())
        except Exception as exc:  # noqa: BLE001
            logger.warning("[agent] turn 发送失败：%s", exc)

    async def close(self, seq: int) -> None:
        """了结一问：发 close 释放 agent 侧状态。失败静默。"""
        if not self.connected or self._ws is None:
            return
        with contextlib.suppress(Exception):
            await self._ws.send(CloseReq(seq=seq).model_dump_json())

    async def disconnect(self) -> None:
        """关连接 + 取消监听。"""
        if self._task is not None:
            self._task.cancel()
        if self._ws is not None:
            await self._ws.close()


__all__ = ["AgentClient", "CONNECT_TIMEOUT_S"]
