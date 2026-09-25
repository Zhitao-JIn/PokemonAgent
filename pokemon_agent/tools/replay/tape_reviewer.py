"""`TapeReviewer`：回放段里顶替人——按序吐出录下的每一轮回话（`review_inject` / `review_audit`）。

与 harness 的 `Reviewer` 协议同形（鸭子类型，不依赖 harness）。
"""

from __future__ import annotations

from typing import Any

from pokemon_agent.schemas.harness import (
    AuditVerdict,
    FromHarnessToReviewerAuditReq,
    FromHarnessToReviewerAuditResp,
    FromHarnessToReviewerInjectReq,
)

from .tape import Tape, event_content


class TapeReviewer:
    """切换前取磁带上的回话，切换后原样转给真的 reviewer。"""

    def __init__(self, real: Any, tape: Tape) -> None:  # noqa: ANN401 —— harness 的 Reviewer
        self._real = real
        self._tape = tape

    def inject(self, req: FromHarnessToReviewerInjectReq) -> str:
        if self._tape.switched:
            return self._real.inject(req)
        return str(event_content(self._tape.peek({"review_inject"}))["reply"])

    def audit(self, req: FromHarnessToReviewerAuditReq) -> FromHarnessToReviewerAuditResp:
        if self._tape.switched:
            return self._real.audit(req)
        body = event_content(self._tape.peek({"review_audit"}))
        return FromHarnessToReviewerAuditResp(
            verdict=AuditVerdict(body["verdict"]), note=body["note"]
        )


__all__ = ["TapeReviewer"]
