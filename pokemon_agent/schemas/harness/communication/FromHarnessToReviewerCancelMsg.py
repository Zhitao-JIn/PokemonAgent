"""Harness 放弃一问的单跳通知；重复取消幂等。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FromHarnessToReviewerCancelMsg(BaseModel):
    """取消不构成答复，也不会影响其他 qid。"""

    model_config = ConfigDict(extra="forbid")
    msg: Literal["cancel"] = "cancel"
    qid: str = Field(min_length=1, max_length=128)
