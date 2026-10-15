"""`FromHarnessToReviewerInjectResp`：`Reviewer.inject()` 交回 harness 的回话。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class FromHarnessToReviewerInjectResp(BaseModel):
    """复核席对一张表单说的话。

    `text` 空串 = 没意见（常态，不是失败）；调用方节点拿非空的 `text` 去带话重问。
    `answered=False`：没人答（超时 / 后端断连 / 无人值守），此时 `text` 恒为空串。
    """

    text: str = Field(default="", description="人或 AI 说的话；空串 = 没意见")
    answered: bool = Field(description="是否有人或 AI 作答；False 表示默认回话，by 为 none")
    by: Literal["human", "agent", "none"] = Field(
        description="回话来源：human 人作答、agent AI 作答、none 无人作答"
    )

    @model_validator(mode="after")
    def validate_answered(self) -> FromHarnessToReviewerInjectResp:
        """回话来源与是否作答必须一致；不一致时拒绝构造。"""
        if self.answered != (self.by != "none"):
            raise ValueError('answered must equal (by != "none")')
        return self


__all__ = ["FromHarnessToReviewerInjectResp"]
