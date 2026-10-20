"""L0 原子采纳规划，保存表与派发顺序；无待办交 judge 复判。"""

from typing import Any

from langgraph.runtime import Runtime
from pydantic import BaseModel

from pokemon_agent.brain import Task
from pokemon_agent.brain.interface import RunPlan
from pokemon_agent.config import PLAN_MAX_NEW_GOALS, REVIEW_AI_INJECT_MAX_ROUNDS
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolPlanOnceReq,
    FromHarnessToBrainToolPlanOnceResp,
    FromHarnessToReviewerInjectReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.harness.domain import GoalEntry, ReviewMark, Termination
from pokemon_agent.schemas.harness.domain.review_context import ReviewContext

from ...budget_nodes import stopped_updates
from ...planning import apply_planning
from ...reviewing import ReviewRound, ask_inject, elicit_with_review
from ..run_state import RunState
from ..runtime import RunRuntime


class PlanDraft(BaseModel):
    """一轮实际请求、提案或预算停止；不提前分配正式身份。"""

    request: FromHarnessToBrainToolPlanOnceReq | None = None
    proposal: RunPlan | None = None
    used: int


def plan_run(state: RunState, runtime: Runtime[RunRuntime]) -> dict[str, Any]:
    """采纳整版后返回新表；无待办是正常调度状态。"""
    deps = runtime.context
    meta = {
        "source": "plan_run",
        "episode_id": state.run_id,
        "task_id": state.run_id,
        "step": state.step,
    }
    draft, note = _elicit(deps, state, meta)
    if draft.proposal is None:
        return {
            **stopped_updates(state, deps, "run", "plan_run", Termination.PLANNING_EXHAUSTED),
            "planning_rounds_used": draft.used,
        }
    proposal = draft.proposal
    entries = _new_entries(state, proposal)
    table, order = apply_planning(state.goals, entries, proposal, state.execution_order)
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.PLAN_VERDICT,
            meta=meta,
            pushed=[e.task.goal for e in entries],
            updates=[
                {"task_id": state.goals[u.index].task.task_id, "status": u.status, "note": u.note}
                for u in proposal.updates
            ],
            why=proposal.why,
            human_note=note,
            planning=proposal,
            planning_round=draft.used,
            execution_order=order,
        )
    )
    return {
        "goals": table,
        "execution_order": order,
        "latest_planning": proposal,
        "planning_rounds_used": draft.used,
        "judge_trigger": "no_pending" if not order else "normal",
    }


def _request(state: RunState, note: str, remaining: int) -> FromHarnessToBrainToolPlanOnceReq:
    """只装本次可见素材；父目标及验收条件显式传递。"""
    ctx = state.plan_ctx
    assert ctx is not None, "plan before perceive"
    req = FromHarnessToBrainToolPlanOnceReq(
        run_id=state.run_id,
        run_goal=state.run_goal,
        plan=state.goals,
        details=ctx.details,
        run_index=ctx.run_index,
        knowledge=ctx.knowledge,
        observation=state.observation,
        objects=ctx.objects,
        max_push=PLAN_MAX_NEW_GOALS,
        last_judge=state.last_judge,
        human_note=note,
        execution_order=state.execution_order,
        remaining_planning_rounds=remaining,
    )
    req.details = ctx.details
    return req


def _elicit(deps: RunRuntime, state: RunState, meta: dict[str, object]) -> tuple[PlanDraft, str]:
    """review 重写占规划轮数；达到上限后不再问模型或 reviewer。"""

    def ask_brain(note: str, number: int) -> PlanDraft:
        used = state.planning_rounds_used + number
        if used > deps.budget.max_planning_rounds:
            return PlanDraft(used=used - 1)
        req = _request(state, note, deps.budget.max_planning_rounds - used + 1)
        return PlanDraft(request=req, proposal=_ask(deps, meta, req).plan, used=used)

    def ask_reviewer(draft: PlanDraft, rounds: ReviewRound) -> ReviewMark:
        if draft.proposal is None:
            return ReviewMark(answered=False, by="none", wait_s=0, round=rounds.number)
        return ask_inject(
            deps.reviewer,
            deps.trace,
            FromHarnessToReviewerInjectReq(
                prompt="审阅本轮目标表新增、修订和派发顺序",
                form=draft.proposal,
                form_kind="RunPlan",
                round=rounds.number,
                max_agent_rounds=rounds.max_agent_rounds,
                context=ReviewContext(
                    layer="run",
                    run_id=state.run_id,
                    episode_id=state.run_id,
                    brain_input=draft.request,
                    goals=state.goals,
                    step=state.step,
                    fail_streak=state.fail_streak,
                ),
            ),
            meta=meta,
            rounds=rounds,
        )

    return elicit_with_review(
        ask_brain,
        ask_reviewer,
        max_agent_rounds=min(
            REVIEW_AI_INJECT_MAX_ROUNDS,
            max(0, deps.budget.max_planning_rounds - state.planning_rounds_used - 1),
        ),
    )


def _ask(
    deps: RunRuntime, meta: dict[str, object], req: FromHarnessToBrainToolPlanOnceReq
) -> FromHarnessToBrainToolPlanOnceResp:
    """全部尝试落账；耗尽显式上抛供父层处理。"""
    try:
        response = deps.planner.plan(req)
    except MaxRetriesExceeded as exc:
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.PLAN_CALL, meta=meta, calls=list(exc.calls)
            )
        )
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(kind=TraceKind.CALL_EXHAUSTED, meta=meta, link="plan")
        )
        raise
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(kind=TraceKind.PLAN_CALL, meta=meta, calls=response.calls)
    )
    return response


def _new_goal_id(state: RunState, offset: int) -> str:
    """跳过所有已用编号，初始外部目标不占生成器编号。"""
    prefix = f"plan-{state.run_id}-"
    suffixes = [
        entry.task.task_id.removeprefix(prefix)
        for entry in state.goals
        if entry.task.task_id.startswith(prefix)
    ]
    used = max((int(suffix) for suffix in suffixes if suffix.isdigit()), default=0)
    return f"{prefix}{used + offset + 1}"


def _new_entries(state: RunState, proposal: RunPlan) -> list[GoalEntry]:
    """采纳后才分配逻辑身份；不修改旧表。"""
    return [
        GoalEntry(
            task=Task(
                task_id=_new_goal_id(state, i),
                goal=item.goal,
                success_criteria=item.success_criteria,
                max_steps=item.budget.limit,
            )
        )
        for i, item in enumerate(proposal.new_items)
    ]
