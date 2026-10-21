"""`review_and_judge` 格（episode 层）：**定案上一个 task + 判停**——与 run 层同构。

⓪定案（表里有 RUNNING 时）：只按 `TaskOutput.success` 盖章（COMPLETED / FAILED）。
无法推进盖 BLOCKED；被打断盖 FAILED，note 写"被打断：…"，不计失败连击。
其余 PENDING 保留，下一次 decompose 决定是否继续、放弃或重开 → 记 `settle_task`。
TaskMemory 的章与任务表均保留机器判定，失败连击沿用 state 原值。

停没停、成没成都由 `termination` 推出（`Settled`）。

①机械：世界结束（`obs.done`）/ 停摆（`fail_streak >= loop.episode_stall_limit`）/
task 数预算尽（`step >= goal.max_steps`）。②模型：派过 task 或规划后无待办时问
"本局目标达成没有"（素材是 perceive 装好的本局 TaskMemory）；判成时亮给人**审**——
认账即 `GOAL_DONE`，推翻则本局继续。审格不重问模型：本局继续跑时，判定员的话与人的
推翻理由写进 `last_judge`，由下一次 `plan_episode` 带给拆解。`reason` 不在这里写。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import (
    AuditVerdict,
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.harness.domain import EntryStatus, TaskOutput, Termination
from pokemon_agent.schemas.harness.domain.review_context import ReviewContext

from ...judging import ask_judger, judge_reason, mechanical_termination, record_verdict
from ...reviewing import audit_judgement
from ..episode_runtime import EpisodeRuntime
from ..episode_state import EpisodeRunState, current_goal, current_knowledge

_SOURCE = "review_and_judge"


def review_and_judge(state: EpisodeRunState, runtime: Runtime[EpisodeRuntime]) -> dict[str, Any]:
    """定案上一个 task，再两段式判停；返回 `{"termination"}` 加定案的增量。"""
    deps = runtime.context
    # 账面步号 = 圈号（0928 定稿）：episode_start 落 0、每圈 +1，同圈所有账共用。
    ep, step = state.episode_id, state.step + 1

    # 步骤 0：刚跑完一个 task 就定案那条 RUNNING（首圈没有）。
    updates: dict[str, object] = {}
    if any(entry.status is EntryStatus.RUNNING for entry in state.tasks):
        updates = _settle(deps, state, state.task_outputs[-1])
    fail_streak = int(updates.get("fail_streak", state.fail_streak))
    stalled = fail_streak >= deps.config.loop.episode_stall_limit

    # 步骤 1：机械三类；还没派过 task 时不问模型。
    termination = mechanical_termination(
        world_ended=state.ep_ctx.observation.done,
        stalled=stalled,
        exhausted=state.step >= state.goal.max_steps,
    )
    verdict = None
    feedback = None

    # 步骤 2：问模型；判成时亮给人审，认账才覆盖机械结论。
    if state.step > 0 or state.judge_trigger == "no_pending":
        meta = {"source": _SOURCE, "episode_id": ep, "task_id": "", "step": step}
        req = FromHarnessToBrainToolJudgeReq(
            goal=current_goal(state),
            latest_planning=state.latest_planning,
            planning_round=state.decompositions_used,
            trigger=state.judge_trigger,
            task_memories=state.ep_ctx.task_memories,
            episode_index=state.ep_ctx.episode_index,
            knowledge="\n\n".join(current_knowledge(state)),
            observation=state.ep_ctx.observation,
            task_table=updates.get("tasks", state.tasks),
        )
        req.task_memories = state.ep_ctx.task_memories
        verdict = ask_judger(deps.judger, deps.trace, req, **meta)
        feedback = audit_judgement(
            deps.reviewer,
            deps.trace,
            verdict,
            run_id=state.run_id,
            meta=meta,
            context=ReviewContext(
                layer="episode",
                run_id=state.run_id,
                episode_id=ep,
                brain_input=req,
                tasks=updates.get("tasks", state.tasks),
                step=step,
                fail_streak=fail_streak,
            ),
        )
        if feedback.audit is AuditVerdict.ACCEPT:
            termination = Termination.BLOCKED if verdict.blocked else Termination.GOAL_DONE
        else:
            updates["last_judge"] = feedback

    # 步骤 3：记结论。
    overturned = feedback is not None and feedback.audit is AuditVerdict.OVERTURN
    reason_for_judge = judge_reason(
        termination,
        verdict,
        not_asked="还没派过 task，不问模型",
        overturn_note=feedback.note if overturned else None,
    )
    record_verdict(
        deps.trace,
        source=_SOURCE,
        episode_id=ep,
        task_id="",
        step=step,
        termination=termination,
        decision=verdict.decision if verdict is not None else None,
        trigger=state.judge_trigger,
        planning_round=state.decompositions_used,
        judge_reason=reason_for_judge,
        fail_streak=state.fail_streak,
        audit=feedback.audit if feedback is not None else None,
        human_note=feedback.note if overturned else "",
    )
    return {
        **updates,
        "termination": termination,
        "judge_reason": reason_for_judge,
        "judge_trigger": "normal",
    }


def _settle(deps: EpisodeRuntime, state: EpisodeRunState, outcome: TaskOutput) -> dict[str, object]:
    """按本次执行结算盖章，保留其他条目，再记 `settle_task`。"""
    index = next(i for i, e in enumerate(state.tasks) if e.status is EntryStatus.RUNNING)
    entry = state.tasks[index]
    assert outcome.entry_id == entry.entry_id and outcome.task_id == entry.last_task_id, (
        "最新结算与 RUNNING 条目对不上"
    )

    # 步骤 1：按机械结算盖章，保留失败连击与被打断的说明。
    status = (
        EntryStatus.COMPLETED
        if outcome.success
        else EntryStatus.BLOCKED
        if outcome.termination is Termination.BLOCKED
        else EntryStatus.FAILED
    )
    fail_streak = state.fail_streak
    interrupted = outcome.termination is Termination.INTERRUPTED
    note = f"被打断：{outcome.judge_reason}" if interrupted else entry.note
    stamped = entry.model_copy(update={"status": status, "overturned": False, "note": note})

    # 步骤 2：保留其他条目，是否放弃由下一次拆解决定。
    tasks = [*state.tasks[:index], stamped, *state.tasks[index + 1 :]]
    abandoned: list[str] = []

    # 步骤 3：记盖章账。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.SETTLE_TASK,
            meta={
                "source": _SOURCE,
                "episode_id": state.episode_id,
                "task_id": "",
                "step": state.step + 1,
            },
            task_entry=stamped,
            audit=None,
            abandoned=abandoned,
            fail_streak=fail_streak,
        )
    )
    return {"tasks": tasks, "fail_streak": fail_streak}


__all__ = ["review_and_judge"]
