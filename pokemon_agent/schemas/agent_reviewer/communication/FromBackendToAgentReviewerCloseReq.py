"""`FromBackendToAgentReviewerCloseReq`：跳 C（后端 → agent）了结一问。无回话。

后端 settle 后发 `close`，agent 释放该 `seq` 的对话状态。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FromBackendToAgentReviewerCloseReq(BaseModel):
    """了结一问：agent 释放该 seq 的对话状态。"""

    msg: Literal["close"] = Field(default="close", description="消息标签：agent 据此分流")
    seq: int = Field(ge=1, description="要释放的是第几问")


# 兼容类型别名。
CloseReq = FromBackendToAgentReviewerCloseReq

__all__ = ["FromBackendToAgentReviewerCloseReq", "CloseReq"]
