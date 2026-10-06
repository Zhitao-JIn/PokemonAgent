"""`FromBackendToAgentReviewerSeedReq`：跳 C（后端 → agent）开一问。

无回话（agent 推 `proposal` 回来）。后端把当前待答的那封跳 B `ask` 与最新一帧原样交给
agent；agent 据此产出首轮 `proposal`。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from pokemon_agent.schemas.review_backend.communication.FromReviewBackendToFrontendAskReq import (
    FromReviewBackendToFrontendAskReq,
)

from .ChatTurn import ChatTurn


class FromBackendToAgentReviewerSeedReq(BaseModel):
    """开一问：把后端 pending 的那封 ask 与一帧画面交给 agent。"""

    msg: Literal["seed"] = Field(default="seed", description="消息标签：agent 据此分流")
    seq: int = Field(ge=1, description="这一问的编号（与跳 B 同号）")
    ask: FromReviewBackendToFrontendAskReq = Field(description="后端 pending 的那封待答")
    frame: str | None = Field(default=None, description="最新一帧（完整 data URI）；无则 None")


# 兼容类型别名（agent 侧按 `ask` 字段调用，不关心它是哪跳的信封）。
SeedReq = FromBackendToAgentReviewerSeedReq

__all__ = ["ChatTurn", "FromBackendToAgentReviewerSeedReq", "SeedReq"]
