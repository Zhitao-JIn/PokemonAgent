"""进程内复核交互契约；线上消息由后续链路层另行封装。"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pokemon_agent.schemas.harness import (
    AuditVerdict,
    FromHarnessToReviewerAuditReq,
    FromHarnessToReviewerAuditResp,
    FromHarnessToReviewerInjectReq,
    FromHarnessToReviewerInjectResp,
)

ReviewRequest = FromHarnessToReviewerInjectReq | FromHarnessToReviewerAuditReq
ReviewResponse = FromHarnessToReviewerInjectResp | FromHarnessToReviewerAuditResp


class ReviewSeats(BaseModel):
    """席位必须显式指定，至少启用一个；无席位场景不启动 reviewer。"""

    human: bool
    ai: bool

    @model_validator(mode="after")
    def require_a_seat(self) -> Self:
        """外部配置错误显式拒绝。"""
        if not (self.human or self.ai):
            raise ValueError("至少启用一个复核席位")
        return self


class InjectAnswer(BaseModel):
    """对插话问的答复；空串表示无意见。"""

    model_config = ConfigDict(extra="forbid")
    text: str = ""


class AuditAnswer(BaseModel):
    """对既有结论表态；推翻必须给非空理由。"""

    model_config = ConfigDict(extra="forbid")
    verdict: AuditVerdict = AuditVerdict.ACCEPT
    note: str = ""

    @model_validator(mode="after")
    def require_overturn_reason(self) -> Self:
        """空白理由不能成为推翻依据。"""
        if self.verdict == AuditVerdict.OVERTURN and not self.note.strip():
            raise ValueError("推翻必须给理由")
        return self


class ReviewProposal(BaseModel):
    """AI 席产出的候选答复；hub 会按当前问种类再次核对。"""

    model_config = ConfigDict(extra="forbid")
    answer: InjectAnswer | AuditAnswer


class Ask(BaseModel):
    """一问的进程内编号与原始素材快照。"""

    seq: int = Field(ge=1)
    request: ReviewRequest

    @property
    def kind(self) -> Literal["inject", "audit"]:
        """问的种类由请求类型推导，不维护第二份可变标签。"""
        return "inject" if isinstance(self.request, FromHarnessToReviewerInjectReq) else "audit"


class SubmitAck(BaseModel):
    """提交成功或拒绝的结果；旧编号与类型不匹配都正常拒绝。"""

    ok: bool
    text: str


class Settle(BaseModel):
    """一问只了结一次；取消与答复互斥，取消不会伪造认账。"""

    seq: int
    response: ReviewResponse | None = None
    cancelled: bool = False
    reason: str = ""

    @model_validator(mode="after")
    def validate_resolution(self) -> Self:
        """取消无答复，正常了结必须有答复。"""
        if self.cancelled != (self.response is None):
            raise ValueError("取消与答复必须互斥")
        return self


class HistoryEntry(BaseModel):
    """有限历史只存问的摘要与结果，不保留整份带图上下文。"""

    seq: int
    kind: Literal["inject", "audit"]
    run_id: str
    prompt: str
    settle: Settle


class Activity(BaseModel):
    """进程内活动记录，不是 trace 业务事件。"""

    seq: int
    action: str
    text: str
