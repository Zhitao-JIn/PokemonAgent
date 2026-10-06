"""`ChatTurn`：跳 C 对话里的一句话——`FromBackendToAgentReviewerTurnReq.delta` 的类型。

agent 进程按 `seq` 持有整段对话（`list[ChatTurn]`）；后端发 `turn` 时只追加一笔增量，
不重发整段。也是 agent 把上一轮自己给的 `proposal` 回灌成 `agent` 角色的来源。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatTurn(BaseModel):
    """对话里的一句话。`role` 取渲染时的身份：system=系统提示、human=人改稿、agent=AI 上轮结论。"""

    role: Literal["system", "human", "agent"] = Field(description="这句话的身份")
    text: str = Field(description="这句话的内容")


__all__ = ["ChatTurn"]
