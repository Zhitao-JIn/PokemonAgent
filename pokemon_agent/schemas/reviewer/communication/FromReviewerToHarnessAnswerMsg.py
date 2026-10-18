"""Reviewer 对一个 qid 的答复；重发只回已缓存的同一答案。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pokemon_agent.schemas.harness import (
    FromHarnessToReviewerAuditResp,
    FromHarnessToReviewerInjectResp,
)


class FromReviewerToHarnessAnswerMsg(BaseModel):
    """答复沿用 harness 信封中的 by / answered 不变式。"""

    model_config = ConfigDict(extra="forbid")
    msg: Literal["answer"] = "answer"
    qid: str = Field(min_length=1, max_length=128)
    resp: FromHarnessToReviewerInjectResp | FromHarnessToReviewerAuditResp
