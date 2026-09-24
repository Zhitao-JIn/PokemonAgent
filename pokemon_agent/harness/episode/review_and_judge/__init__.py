"""`review_and_judge` 格（episode 层）：**定案上一个 task + 判停**——与 run 层同构。

⓪定案（表里有 RUNNING 时）：按 `TaskOutput` 盖章（COMPLETED / FAILED）→ 亮给人审，推翻则
盖反面、`overturned=True`、修正失败连击 → 定案为失败时，把剩下的 PENDING 条目标 ABANDONED
（它们是按"上一个会成"拆的，前提已失效；`plan_episode` 会带着这张表重拆）→ 记 `settle_task`。
TaskMemory 的章保留机器判定，任务表是最终定案。

停没停、成没成都由 `termination` 推出（`Settled`）。

①机械：世界结束（`obs.done`）/ 停摆（`fail_streak >= EPISODE_STALL_LIMIT`）/
task 数预算尽（`step >= goal.max_steps`）。②模型：派过至少一个 task 之后问
"本局目标达成没有"（素材是 perceive 装好的本局 TaskMemory），判成即 `GOAL_DONE`；
人可插话，带话重问直到没意见。`reason` 不在这里写。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.config import EPISODE_STALL_LIMIT
from pokemon_agent.schemas.harness import (
    AuditVerdict,
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToReviewerAuditReq,
    FromHarnessToReviewerInjectReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.harness.domain import EntryStatus, TaskOutput, Termination

from ...judging import ask_judger, judge_reason, mechanical_termination, record_verdict
from ..episode_runtime import EpisodeRuntime
from ..episode_state import EpisodeRunState, current_goal

_SOURCE = "review_and_judge"


def review_and_judge(state: EpisodeRunState, runtime: Runtime[EpisodeRuntime]) -> dict[str, Any]:
    """定案上一个 task，再两段式判停；返回 `{"termination"}` 加定案的增量。"""
    deps = runtime.context
    ep, step = state.episode_id, state.ep_ctx.observation.step

    # 步骤 0：刚跑完一个 task 就定案那条 RUNNING（首圈没有）。
    updates: dict[str, object] = {}
    if any(entry.status is EntryStatus.RUNNING for entry in state.tasks):
        updates = _settle(deps, state, state.task_outputs[-1])
    fail_streak = int(updates.get("fail_streak", state.fail_streak))
    stalled = fail_streak >= EPISODE_STALL_LIMIT

    # 步骤 1：机械三类；还没派过 task 时不问模型。
    termination = mechanical_termination(
        world_ended=state.ep_ctx.observation.done,
        stalled=stalled,
        exhausted=state.step >= state.goal.max_steps,
    )
    verdict = None
    note = ""

    # 步骤 2：问模型（带插话循环），判成覆盖机械结论。
    if state.step > 0:
        while True:
            req = FromHarnessToBrainToolJudgeReq(
                goal=current_goal(state),
                task_memories=state.ep_ctx.task_memories,
                task_table=updates.get("tasks", state.tasks),
                human_note=note,
            )
            verdict = ask_judger(
                deps.judger, deps.trace, req, source=_SOURCE, episode_id=ep, task_id=ep, step=step
            )
            reply = deps.reviewer.inject(
                FromHarnessToReviewerInjectReq(
                    prompt=f"请审本局判定（第 {state.step} 个 task 之后："
                    f"{'判成' if verdict.done else '判未成'}）",
                    form=verdict,
                    form_kind="JudgeVerdict",
                )
            )
            if not reply:
                break
            note = reply
        if verdict.done:
            termination = Termination.GOAL_DONE

    # 步骤 3：记结论。
    reason_for_judge = judge_reason(termination, verdict, not_asked="还没派过 task，不问模型")
    record_verdict(
        deps.trace,
        source=_SOURCE,
        episode_id=ep,
        task_id=ep,
        step=step,
        termination=termination,
        judge_reason=reason_for_judge,
        fail_streak=state.fail_streak,
        verdict=verdict,
        human_note=note,
    )
    return {**updates, "termination": termination, "judge_reason": reason_for_judge}


def _settle(deps: EpisodeRuntime, state: EpisodeRunState, outcome: TaskOutput) -> dict[str, object]:
    """盖章 → 人审（推翻则盖反面）→ 失败则放弃剩余 PENDING → 记 `settle_task`。"""
    index = next(i for i, e in enumerate(state.tasks) if e.status is EntryStatus.RUNNING)
    entry = state.tasks[index]
    assert outcome.task_id == entry.task.task_id, "最新结算与 RUNNING 条目对不上"

    # 步骤 1：机械盖章；亮给人审，推翻则盖反面、失败连击跟着修正。
    status = EntryStatus.COMPLETED if outcome.success else EntryStatus.FAILED
    resp = deps.reviewer.audit(
        FromHarnessToReviewerAuditReq(
            run_id=state.run_id,
            episode_id=state.episode_id,
            task_id=entry.task.task_id,
            outcome=outcome,
            events=deps.trace.read_events(
                {
                    "run_id": state.run_id,
                    "episode_id": state.episode_id,
                    "task_id": entry.task.task_id,
                }
            ),
        )
    )
    overturned = resp.verdict is AuditVerdict.OVERTURN
    fail_streak = state.fail_streak
    if overturned:
        status = EntryStatus.FAILED if status is EntryStatus.COMPLETED else EntryStatus.COMPLETED
        fail_streak = 0 if status is EntryStatus.COMPLETED else fail_streak + 1
    stamped = entry.model_copy(
        update={
            "status": status,
            "overturned": overturned,
            "note": resp.note if overturned and resp.note else entry.note,
        }
    )

    # 步骤 2：定案为失败 → 剩下的 PENDING 前提失效，标 ABANDONED。
    tasks = [*state.tasks[:index], stamped, *state.tasks[index + 1 :]]
    abandoned: list[str] = []
    if status is EntryStatus.FAILED:
        note = f"{entry.task.task_id} 失败，这一版剩下的前提已失效"
        for i, other in enumerate(tasks):
            if other.status is EntryStatus.PENDING:
                tasks[i] = other.model_copy(update={"status": EntryStatus.ABANDONED, "note": note})
                abandoned.append(other.task.task_id)

    # 步骤 3：记盖章账。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.SETTLE_TASK,
            meta={
                "source": _SOURCE,
                "episode_id": state.episode_id,
                "task_id": state.episode_id,
                "step": state.ep_ctx.observation.step,
            },
            task_entry=stamped,
            audit=resp.verdict.value,
            abandoned=abandoned,
            fail_streak=fail_streak,
        )
    )
    return {"tasks": tasks, "fail_streak": fail_streak}


__all__ = ["review_and_judge"]
