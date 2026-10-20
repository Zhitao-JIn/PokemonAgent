"""Run 侧的协议校验与默认答复，不依赖 harness 或 reviewer 实现。"""

from concurrent.futures import Future
from dataclasses import dataclass

from pokemon_agent.schemas.harness import (
    AuditVerdict,
    FromHarnessToReviewerAuditResp,
    FromHarnessToReviewerInjectResp,
)
from pokemon_agent.schemas.harness.communication.FromHarnessToReviewerAskMsg import (
    FromHarnessToReviewerAskMsg,
)
from pokemon_agent.schemas.reviewer.communication import FromReviewerToHarnessAnswerMsg
from pokemon_agent.schemas.reviewer.interaction import ReviewResponse


class ReviewerProtocolError(ValueError):
    """服务回话违反本跳契约；连接重建时仍不能把它视为有效答复。"""


@dataclass
class Pending:
    """同步调用方与后台线程共享的一问，由适配器的锁保护。"""

    wire: FromHarnessToReviewerAskMsg
    future: Future[ReviewResponse]


def default_response(op: str) -> ReviewResponse:
    """仅在明确关闭或已知 AI 模式的断线预算耗尽时，按无人作答返回。"""
    if op == "inject":
        return FromHarnessToReviewerInjectResp(text="", answered=False, by="none")
    return FromHarnessToReviewerAuditResp(verdict=AuditVerdict.ACCEPT, answered=False, by="none")


def matching_response(pending: Pending, message: FromReviewerToHarnessAnswerMsg) -> ReviewResponse:
    """相同 qid 的答复还必须与操作匹配；不匹配则不能解除同步等待。"""
    if (pending.wire.op == "inject") != isinstance(message.resp, FromHarnessToReviewerInjectResp):
        raise ReviewerProtocolError("答复类型与请求不匹配")
    return message.resp
