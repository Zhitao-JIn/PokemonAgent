"""`agent_reviewer` 的 WebSocket 服务端（跳 C 的 agent 侧）。

收 `seed`/`turn`/`close`，推 `proposal`。

后端是 WS 客户端、agent 是 WS 服务端。后端与 agent 之间**只有一条长连接**：seed/turn/close
都发在同一条连接上，agent 把每轮的 `proposal` 在同一条连接上推回。连接断 = agent 崩，
后端据其缺失按"没人答"处理（不重连，agent 重启只服务新 seq）。
"""

from __future__ import annotations

import json
import logging

from websockets.asyncio.server import ServerConnection, serve

from pokemon_agent.agent_reviewer.agent import AgentReviewer
from pokemon_agent.schemas.agent_reviewer import (
    MSG_CLOSE,
    MSG_SEED,
    MSG_TURN,
    CloseReq,
    ProposalMsg,
    SeedReq,
    TurnReq,
)

logger = logging.getLogger(__name__)


def _handler(agent: AgentReviewer) -> callable:
    """返回一个 websockets 连接处理函数：按 `msg` 分流调 agent 并回 `proposal`。"""

    async def handler(conn: ServerConnection) -> None:
        async for raw in conn:
            try:
                data = json.loads(raw)
            except (ValueError, TypeError):
                logger.warning("[agent] 收来看不懂的消息，丢弃")
                continue
            msg = data.get("msg")
            try:
                if msg == MSG_SEED:
                    req = SeedReq.model_validate(data)
                    prop = agent.seed(req.ask, req.frame)
                    await conn.send(
                        ProposalMsg(seq=req.seq, proposal=prop, round=0).model_dump_json()
                    )
                elif msg == MSG_TURN:
                    req = TurnReq.model_validate(data)
                    prop = agent.turn(req.seq, req.delta, req.frame)
                    await conn.send(
                        ProposalMsg(seq=req.seq, proposal=prop, round=0).model_dump_json()
                    )
                elif msg == MSG_CLOSE:
                    req = CloseReq.model_validate(data)
                    agent.close(req.seq)
                    # close 无回话。
                else:
                    logger.warning("[agent] 收来未知消息：%r", msg)
            except Exception as exc:  # noqa: BLE001  agent 崩不能拖垮连接
                logger.warning("[agent] 处理 %r 出错：%s", msg, exc)

    return handler


async def serve_agent(agent: AgentReviewer, host: str, port: int) -> None:
    """起 agent WS 服务并一直挂着（由 `__main__` 的 `asyncio.run` 驱动）。"""
    async with serve(_handler(agent), host, port, max_size=None) as server:
        logger.info("[agent] 已启动：ws://%s:%s", host, port)
        await server.serve_forever()


__all__ = ["serve_agent"]
