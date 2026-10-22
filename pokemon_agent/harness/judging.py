"""三层 `review_and_judge` 共用的两件事：机械三类的判定顺序、问 judger 并记账。

与 `compose.py` 同级的共享层：只依赖 tools 门面与 schemas，不认识任何一层的 state。
"""

from __future__ import annotations

from pokemon_agent.direct.interface import JudgePort, TraceToolPort
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    AuditVerdict,
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.harness.domain import Termination


def mechanical_termination(
    *, world_ended: bool, stalled: bool, exhausted: bool
) -> Termination | None:
    """机械三类按固定优先级取第一条成立的：世界结束 > 停摆 > 预算尽；都不成立返回 None。"""
    if world_ended:
        return Termination.WORLD_ENDED
    if stalled:
        return Termination.STALLED
    if exhausted:
        return Termination.BUDGET_EXHAUSTED
    return None


def ask_judger(
    judger: JudgePort,
    trace: TraceToolPort,
    req: FromHarnessToBrainToolJudgeReq,
    *,
    source: str,
    episode_id: str,
    task_id: str,
    step: int,
) -> FromHarnessToBrainToolJudgeResp:
    """问一次 judger 并记 `judge_call`；重试耗尽时记整条账 + `call_exhausted` 后原样上抛。"""
    meta = {"source": source, "episode_id": episode_id, "task_id": task_id, "step": step}
    try:
        verdict = judger.judge(req)
    except MaxRetriesExceeded as exc:
        trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.JUDGE_CALL, meta=meta, calls=list(exc.calls)
            )
        )
        trace.append(
            FromHarnessToTraceToolAppendReq(kind=TraceKind.CALL_EXHAUSTED, meta=meta, link="judge")
        )
        raise
    trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.JUDGE_CALL, meta=meta, calls=verdict.calls, why=verdict.why
        )
    )
    return verdict


def judge_reason(
    termination: Termination | None,
    verdict: FromHarnessToBrainToolJudgeResp | None,
    *,
    not_asked: str,
    overturn_note: str | None = None,
) -> str:
    """本层这一圈的**判定依据**（`judge_reason`）——与 `*_done` 里 LLM 写的结论 `reason` 分开。

    判成（`goal_done`）或判被打断（`interrupted`）时就是判定员给的理由；机械判停时先写机械类别，再附判定员的话
    （没问模型时附 `not_asked`）；还没停时就是判定员说"没成"的理由。
    overturn_note：人推翻了判定员的「已达成」时给的理由（None = 没推翻）；推翻时依据写成
    「被人推翻：理由；判定员原话」。
    """
    if (
        termination in (Termination.GOAL_DONE, Termination.INTERRUPTED, Termination.BLOCKED)
        and verdict is not None
    ):
        return verdict.why
    said = verdict.why if verdict is not None else not_asked
    if overturn_note is not None and verdict is not None:
        note = overturn_note or "（未给理由）"
        said = f"判定员语义结论被人推翻：{note}；判定员原话：{verdict.why}"
    return f"机械判停：{termination.value}；{said}" if termination is not None else said


def record_verdict(
    trace: TraceToolPort,
    *,
    source: str,
    episode_id: str,
    task_id: str,
    step: int,
    termination: Termination | None,
    judge_reason: str,
    fail_streak: int | None = None,
    audit: AuditVerdict | None = None,
    human_note: str = "",
    decision: str | None = None,
    trigger: str = "normal",
    planning_round: int | None = None,
) -> None:
    """记一条 `judge_verdict`。

    audit：人对这次裁决的表态（None = 没问人）；human_note：人推翻时的理由。
    那次调用的请求与原文在同一步的 `judge_call` 账里，这里不再复制（2026-09-27）。
    """
    trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.JUDGE_VERDICT,
            meta={"source": source, "episode_id": episode_id, "task_id": task_id, "step": step},
            termination=termination,
            decision=decision,
            judge_trigger=trigger,
            planning_round=planning_round,
            fail_streak=fail_streak,
            judge_reason=judge_reason,
            audit=audit.value if audit is not None else None,
            human_note=human_note,
        )
    )


__all__ = ["ask_judger", "judge_reason", "mechanical_termination", "record_verdict"]
