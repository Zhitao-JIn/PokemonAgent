"""task 判停：机械边界、模型裁决与可选复核；反馈随状态保存并进入下一次决策。"""

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.brain import Goal
from pokemon_agent.schemas.harness import (
    AuditVerdict,
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToBrainToolJudgeResp,
)
from pokemon_agent.schemas.harness.domain import JudgeFeedback, Termination
from pokemon_agent.schemas.harness.domain.review_context import ReviewContext

from ...judging import ask_judger, judge_reason, mechanical_termination, record_verdict
from ...reviewing import audit_judgement
from ..task_runtime import TaskRuntime
from ..task_state import TaskState

_SOURCE = "task.review_and_judge"


def review_and_judge(state: TaskState, runtime: Runtime[TaskRuntime]) -> dict[str, Any]:
    """第零键不问模型；启用 task 审点后，判成只有认账才覆盖机械边界。"""
    deps = runtime.context
    meta = {
        "source": _SOURCE,
        "episode_id": state.episode_id,
        "task_id": state.task.task_id,
        "step": state.step + 1,
    }
    termination = mechanical_termination(
        world_ended=state.task_ctx.observation.done,
        stalled=state.stall_count >= deps.config.loop.act_stall_limit,
        exhausted=state.step >= state.task.max_steps,
    )
    verdict = None
    feedback = None
    if state.step > 0:
        req = _request(state)
        verdict = ask_judger(deps.judger, deps.trace, req, **meta)
        if "task" in deps.config.review.layers:
            feedback = audit_judgement(
                deps.reviewer,
                deps.trace,
                verdict,
                run_id=state.run_id,
                meta=meta,
                context=ReviewContext(
                    layer="task",
                    run_id=state.run_id,
                    episode_id=state.episode_id,
                    task_id=state.task.task_id,
                    brain_input=req,
                    step=meta["step"],
                    fail_streak=state.stall_count,
                ),
            )
        if (verdict.done or verdict.blocked) and (
            feedback is None or feedback.audit is AuditVerdict.ACCEPT
        ):
            termination = Termination.BLOCKED if verdict.blocked else Termination.GOAL_DONE
        elif not verdict.done and verdict.interrupted:
            termination = Termination.INTERRUPTED
    return _finish(state, deps, termination, verdict, feedback)


def _request(state: TaskState) -> FromHarnessToBrainToolJudgeReq:
    """只装本 task 的目标、全部动作、背景与知识；绑定原始只读 history。"""
    req = FromHarnessToBrainToolJudgeReq(
        goal=Goal(goal=state.task.goal, criteria=state.task.success_criteria),
        history=state.task_ctx.act_memories,
        allow_interrupt=True,
        task_index=state.task_index,
        knowledge="\n\n".join(state.knowledge),
    )
    req.history = state.task_ctx.act_memories
    return req


def _finish(
    state: TaskState,
    deps: TaskRuntime,
    termination: Termination | None,
    verdict: FromHarnessToBrainToolJudgeResp | None,
    feedback: JudgeFeedback | None,
) -> dict[str, Any]:
    """记录原有结论账和可选复核结果；关闭审点时不写反馈状态。"""
    overturned = feedback is not None and feedback.audit is AuditVerdict.OVERTURN
    reason = judge_reason(
        termination,
        verdict,
        not_asked="第 0 键不问模型",
        overturn_note=feedback.note if overturned else None,
    )
    record_verdict(
        deps.trace,
        source=_SOURCE,
        episode_id=state.episode_id,
        task_id=state.task.task_id,
        step=state.step + 1,
        termination=termination,
        decision=verdict.decision if verdict is not None else None,
        judge_reason=reason,
        audit=feedback.audit if feedback is not None else None,
        human_note=feedback.note if overturned else "",
    )
    updates: dict[str, Any] = {"termination": termination, "judge_reason": reason}
    if feedback is not None:
        updates["last_judge"] = feedback
    return updates


__all__ = ["review_and_judge"]
