"""`FromBackendToAgentReviewerTurnReq`：跳 C（后端 → agent）追加一笔人改稿。无回话。

后端把网页「发给 AI」的 `discuss` 转成一笔 `delta` 追加进该 `seq` 的对话，
agent 推回新一轮 `proposal`（round+1）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .ChatTurn import ChatTurn


class FromBackendToAgentReviewerTurnReq(BaseModel):
    """追加一笔人改稿：agent 在已有对话上续推新一轮 proposal。"""

    msg: Literal["turn"] = Field(default="turn", description="消息标签：agent 据此分流")
    seq: int = Field(ge=1, description="追加到哪一问")
    delta: ChatTurn = Field(description="人这一轮发来的一句话")
    frame: str | None = Field(default=None, description="最新一帧（完整 data URI）；无则 None")


# 兼容类型别名。
TurnReq = FromBackendToAgentReviewerTurnReq

__all__ = ["ChatTurn", "FromBackendToAgentReviewerTurnReq", "TurnReq"]
