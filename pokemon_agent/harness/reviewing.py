"""`ask_inject` / `ask_audit`：**问人**的唯一入口，run 与 episode 两层共用。

与 `sensing.py` / `judging.py` 同级的共享层：只依赖 reviewer 接口、trace 门面与 schemas，
不认识任何一层的 state。问完即记一笔 `review_inject` / `review_audit`——插话可以连问多轮，
每一轮的回话都要在账上有独立一笔，回放才能按序喂回（`docs/checkpoint/intent.md` C10）。
"""

from __future__ import annotations

from typing import Any

from pokemon_agent.schemas.harness import (
    FromHarnessToReviewerAuditReq,
    FromHarnessToReviewerAuditResp,
    FromHarnessToReviewerInjectReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.harness.domain import ReviewMark
from pokemon_agent.tools.interface import TraceToolPort

from .interface.reviewer import Reviewer


def ask_inject(
    reviewer: Reviewer,
    trace: TraceToolPort,
    req: FromHarnessToReviewerInjectReq,
    *,
    meta: dict[str, Any],
) -> str:
    """把一张表单亮给人，记一笔 `review_inject`，返回人说的话（空串 = 没意见）。"""
    reply = reviewer.inject(req)
    trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.REVIEW_INJECT,
            meta=meta,
            review=ReviewMark(form_kind=req.form_kind, reply=reply),
        )
    )
    return reply


def ask_audit(
    reviewer: Reviewer,
    trace: TraceToolPort,
    req: FromHarnessToReviewerAuditReq,
    *,
    meta: dict[str, Any],
) -> FromHarnessToReviewerAuditResp:
    """把一条结论亮给人审，记一笔 `review_audit`，返回表态。"""
    resp = reviewer.audit(req)
    trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.REVIEW_AUDIT,
            meta=meta,
            review=ReviewMark(verdict=resp.verdict.value, note=resp.note),
        )
    )
    return resp


__all__ = ["ask_audit", "ask_inject"]
