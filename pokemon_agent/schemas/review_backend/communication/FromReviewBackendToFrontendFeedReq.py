"""`FromReviewBackendToFrontendFeedReq`：跳 B（后端 → 网页）转播一条实时 trace。无回话。

后端不解析事件，原样转播；网页按 `kind` 分栏（`sense_frame` 的画面、其余进时间线）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from pokemon_agent.schemas.harness.domain.trace_event import TraceEvent


class FromReviewBackendToFrontendFeedReq(BaseModel):
    """一条事件。"""

    msg: Literal["feed"] = Field(default="feed", description="消息标签：`/ui` 上据此分流")
    run_id: str = Field(description="哪次 run 的账")
    event: TraceEvent = Field(description="与盘上同形的事件")


__all__ = ["FromReviewBackendToFrontendFeedReq"]
