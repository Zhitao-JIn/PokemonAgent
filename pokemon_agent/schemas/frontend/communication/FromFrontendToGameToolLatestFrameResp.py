"""Frontend → GameTools 的 latest_frame 交互：取最新帧响应。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromFrontendToGameToolLatestFrameResp(BaseModel):
    """最新一帧 PNG；管道尚无新帧时 `frame_png` 为 None（SSE 侧跳过本次推帧）。"""

    frame_png: bytes | None = Field(default=None, description="最新一帧 PNG；None = 无新帧")
