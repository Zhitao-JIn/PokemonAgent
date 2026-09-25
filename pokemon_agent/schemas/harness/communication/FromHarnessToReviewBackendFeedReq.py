"""`FromHarnessToReviewBackendFeedReq`：跳 A（源程序 → 后端）的**实时 trace**。

每落一条账推一封，经 WebSocket `/feed` 单向发送，无回话。盘上的账仍是唯一真相，
这一路只供网页实时看，丢了不补。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.harness.domain.trace_event import TraceEvent


class FromHarnessToReviewBackendFeedReq(BaseModel):
    """一条刚落盘的事件。"""

    run_id: str = Field(description="这次 run 的标识")
    event: TraceEvent = Field(description="与盘上同形的事件（`meta` / `content` 是 JSON 字符串）")


__all__ = ["FromHarnessToReviewBackendFeedReq"]
