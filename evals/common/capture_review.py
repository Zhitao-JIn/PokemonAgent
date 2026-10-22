"""旁路记录 reviewer 的询问与结束，并单独核对等待账。"""

import json
from pathlib import Path

from pydantic import BaseModel, Field

from pokemon_agent.harness.interface.reviewer import Reviewer
from pokemon_agent.schemas.harness import (
    FromHarnessToReviewerAuditReq,
    FromHarnessToReviewerAuditResp,
    FromHarnessToReviewerInjectReq,
    FromHarnessToReviewerInjectResp,
)

from .invocation import RecordingInvocation


class RecordedReviewer:
    """相同 Reviewer 协议；保持原请求、返回和异常。"""

    def __init__(self, inner: Reviewer, directory: Path) -> None:
        """原 reviewer 从装配好的 runtime 注入，不新建外部依赖。"""
        self._inject = RecordingInvocation(inner.inject, directory / "inject")
        self._audit = RecordingInvocation(inner.audit, directory / "audit")

    def inject(self, request: FromHarnessToReviewerInjectReq) -> FromHarnessToReviewerInjectResp:
        """记录插话等待，包括失败或未完成。"""
        return self._inject(request)

    def audit(self, request: FromHarnessToReviewerAuditReq) -> FromHarnessToReviewerAuditResp:
        """记录 judge 定案的审查等待。"""
        return self._audit(request)


class ReviewWaitAudit(BaseModel):
    """询问、完成、pending 与生产等待账分别计数。"""

    not_requested: dict[str, int] = Field(default_factory=dict)
    requested: int = 0
    completed: int = 0
    pending: int = 0
    failed: int = 0
    trace_marks: int = 0
    trace_wait_s: float = 0
    port_elapsed_s: float = 0
    missing: int = 0
    by_port: dict[str, int] = Field(default_factory=dict)


def audit_review(directory: Path) -> ReviewWaitAudit:
    """只读本次 reviewer 录制与 trace；不把 Port 总耗时当作 wait_s。"""
    audit = ReviewWaitAudit()
    for request in (directory / "review_calls").glob("*/*/*.request.json"):
        audit.requested += 1
        port = request.parent.relative_to(directory / "review_calls").as_posix()
        audit.by_port[port] = audit.by_port.get(port, 0) + 1
        ending = request.with_name(request.name.replace(".request.json", ".end.json"))
        if not ending.exists():
            audit.pending += 1
            continue
        value = json.loads(ending.read_text("utf-8"))
        audit.completed += value["status"] == "success"
        audit.failed += value["status"] != "success"
        audit.port_elapsed_s += value["elapsed_s"]
    for path in (directory / "trace").glob("*.json"):
        event = json.loads(path.read_text("utf-8"))
        if event["kind"] not in ("review_inject", "review_audit"):
            continue
        content = event["content"]
        if isinstance(content, str):
            content = json.loads(content)
        if "wait_s" not in content:
            audit.missing += 1
        else:
            audit.trace_marks += 1
            audit.trace_wait_s += float(content["wait_s"])
    for port in (directory / "brain_calls").glob("*/*"):
        if port.name not in ("judge", "plan", "decompose"):
            continue
        review_port = port.parent.name + "/" + ("audit" if port.name == "judge" else "inject")
        opportunities = len(list(port.glob("*.request.json")))
        audit.not_requested[port.relative_to(directory / "brain_calls").as_posix()] = max(
            0, opportunities - audit.by_port.get(review_port, 0)
        )
    audit.missing += abs(audit.trace_marks - audit.completed)
    return audit
