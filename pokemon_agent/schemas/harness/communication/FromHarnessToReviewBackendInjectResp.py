"""`FromHarnessToReviewBackendInjectResp`：跳 A（后端 → 源程序）的插话回话。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToReviewBackendInjectResp(BaseModel):
    """后端交回的回话。`seq` 是后端给这一问编的号，进源程序日志。"""

    seq: int = Field(ge=1, description="后端给这一问的编号（全局单调、跨 run）")
    text: str = Field(default="", description="人说的话；空串 = 没意见")
    answered: bool = Field(description="人真的答了；False = 超时，回的是空串")


__all__ = ["FromHarnessToReviewBackendInjectResp"]
