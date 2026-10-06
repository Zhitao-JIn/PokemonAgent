"""`FromFrontendToReviewBackendDiscussReq`：跳 B（网页 → 后端）把人改过的结论回灌给 AI 复核席。

无回话。后端收到后调 agent 进程的 `turn`，agent 推回新的一笔 `proposal`（round+1）。
同一 `seq` 正在处理时忽略后续。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FromFrontendToReviewBackendDiscussReq(BaseModel):
    """人把结论框里的话发给 AI，请它再磨一轮。"""

    msg: Literal["discuss"] = Field(default="discuss", description="消息标签：`/ui` 上据此分流")
    seq: int = Field(ge=1, description="发给哪一问的 AI")
    text: str = Field(description="人填进结论框、要发给 AI 的话")


__all__ = ["FromFrontendToReviewBackendDiscussReq"]
