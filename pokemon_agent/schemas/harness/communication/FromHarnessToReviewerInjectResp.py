"""`FromHarnessToReviewerInjectResp`：`Reviewer.inject()` 交回 harness 的回话。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToReviewerInjectResp(BaseModel):
    """人对一张表单说的话。

    `text` 空串 = 没意见（常态，不是失败）；调用方节点拿非空的 `text` 去带话重问。
    `answered=False`：没人答（超时 / 后端断连 / 无人值守），此时 `text` 恒为空串。
    """

    text: str = Field(default="", description="人说的话；空串 = 没意见")
    answered: bool = Field(description="人真的答了；False = 回的是默认值（空串）")


__all__ = ["FromHarnessToReviewerInjectResp"]
