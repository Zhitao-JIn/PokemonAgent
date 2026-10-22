"""`ask_inject` / `audit_judgement`：**问人**的唯一入口，run 与 episode 两层共用。

与 `sensing.py` / `judging.py` 同级的共享层：只依赖 reviewer 接口、trace 门面与 schemas，
不认识任何一层的 state。问完即记一笔 `review_inject` / `review_audit`——插话可以连问多轮，
每一轮的回话都要在账上有独立一笔，人在环这一路才可审计。
两本账都带 `answered`（人真答了还是默认值）与 `wait_s`（人花了多久）；
审的账还带被审对象的种类（`form_kind`），两个审点均只审 judge 的「已达成」裁决。
"""

from __future__ import annotations

import time
from typing import Any

from pokemon_agent.direct.interface import TraceToolPort
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToReviewerAuditReq,
    FromHarnessToReviewerInjectReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.harness.domain import JudgeFeedback, ReviewMark
from pokemon_agent.schemas.harness.domain.review_context import ReviewContext

from .interface.reviewer import Reviewer
from .review_loop import ReviewRound, elicit_with_review
from .review_render import outcome_kind


def ask_inject(
    reviewer: Reviewer,
    trace: TraceToolPort,
    req: FromHarnessToReviewerInjectReq,
    *,
    meta: dict[str, Any],
    rounds: ReviewRound,
) -> ReviewMark:
    """亮表并返回同一份落账素材；AI 到顶时保留原话，标 capped，意见不再生效。

    前置条件：请求中的轮次、上限与本轮上下文相同；不吞 reviewer 的异常。
    后置条件：每次询问恰落一账，人的意见和空回话不标 capped。
    """
    assert req.round == rounds.number and req.max_agent_rounds == rounds.max_agent_rounds
    asked_at = time.monotonic()
    resp = reviewer.inject(req)
    mark = ReviewMark(
        form_kind=req.form_kind,
        reply=resp.text,
        answered=resp.answered,
        by=resp.by,
        wait_s=time.monotonic() - asked_at,
        capped=bool(
            resp.text
            and resp.by == "agent"
            and rounds.consecutive_agent_rounds >= rounds.max_agent_rounds
        ),
        round=req.round,
    )
    trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.REVIEW_INJECT,
            meta=meta,
            review=mark,
        )
    )
    return mark


def audit_judgement(
    reviewer: Reviewer,
    trace: TraceToolPort,
    verdict: FromHarnessToBrainToolJudgeResp,
    *,
    run_id: str,
    context: ReviewContext,
    meta: dict[str, Any],
) -> JudgeFeedback:
    """消费本次完整请求并返回结果；失败保留调用账，输入不被修改。"""
    if not (verdict.done or verdict.blocked):
        return JudgeFeedback(decision=verdict.decision, why=verdict.why)
    # 步骤 1：取本层刚记的 judge_call 当依据。
    events = [
        event
        for event in trace.read_events({"run_id": run_id, **meta})
        if event.kind == TraceKind.JUDGE_CALL
    ]
    # 步骤 2：亮给人审。
    req = FromHarnessToReviewerAuditReq(
        run_id=run_id,
        episode_id=meta["episode_id"],
        outcome=verdict,
        events=events[-1:],
        context=context,
    )
    asked_at = time.monotonic()
    resp = reviewer.audit(req)
    trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.REVIEW_AUDIT,
            meta=meta,
            review=ReviewMark(
                form_kind=outcome_kind(req.outcome),
                verdict=resp.verdict.value,
                note=resp.note,
                answered=resp.answered,
                by=resp.by,
                wait_s=time.monotonic() - asked_at,
            ),
        )
    )
    return JudgeFeedback(
        decision=verdict.decision, why=verdict.why, audit=resp.verdict, note=resp.note
    )


__all__ = ["ReviewRound", "ask_inject", "audit_judgement", "elicit_with_review"]
