"""Harness 发起的单跳复核请求，qid 在重连重发中保持不变。"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .FromHarnessToReviewerAuditReq import FromHarnessToReviewerAuditReq
from .FromHarnessToReviewerInjectReq import FromHarnessToReviewerInjectReq


class FromHarnessToReviewerAskMsg(BaseModel):
    """请求种类必须与信封标签一致，非法线上输入显式拒绝。"""

    model_config = ConfigDict(extra="forbid")
    msg: Literal["ask"] = "ask"
    qid: str = Field(min_length=1, max_length=128)
    op: Literal["inject", "audit"]
    req: FromHarnessToReviewerInjectReq | FromHarnessToReviewerAuditReq

    @model_validator(mode="after")
    def validate_operation(self) -> Self:
        """标签不允许把审问当作插话，或反过来。"""
        if (self.op == "inject") != isinstance(self.req, FromHarnessToReviewerInjectReq):
            raise ValueError("op 与请求类型不匹配")
        return self
