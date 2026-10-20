"""L1 原子采纳任务表规划；已有待办仍可修订，无待办交 judge。"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime
from pydantic import BaseModel

from pokemon_agent.brain import Task
from pokemon_agent.brain.interface import Decomposition
from pokemon_agent.config import EPISODE_MAX_TASKS_PER_PLAN, REVIEW_AI_INJECT_MAX_ROUNDS
from pokemon_agent.errors import BudgetExhausted, MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolDecomposeReq,
    FromHarnessToBrainToolDecomposeResp,
    FromHarnessToReviewerInjectReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.harness.domain import ReviewMark, TaskEntry, Termination
from pokemon_agent.schemas.harness.domain.review_context import ReviewContext

from ...budget_nodes import stopped_updates
from ...planning import apply_planning
from ...reviewing import ReviewRound, ask_inject, elicit_with_review
from ..episode_runtime import EpisodeRuntime
from ..episode_state import EpisodeRunState, current_goal, current_knowledge

EXHAUSTED_REASON = "拆解耗尽重试，没有 task 可派"
"""拆解耗尽时写进 `judge_reason` 的机械说明（本局以 `Termination.ERROR` 收尾）。"""


class Elicited(BaseModel):
    """一次逻辑拆解的结果与已用轮数；内部模型重试不增加轮数。"""

    response: FromHarnessToBrainToolDecomposeResp | None = None
    request: FromHarnessToBrainToolDecomposeReq | None = None
    note: str
    used: int
    termination: Termination | None = None


def plan_episode(state: EpisodeRunState, runtime: Runtime[EpisodeRuntime]) -> dict[str, Any]:
    """消费本次完整请求并返回结果；失败保留调用账，输入不被修改。"""
    deps = runtime.context
    meta = {
        "source": "plan_episode",
        "episode_id": state.episode_id,
        "task_id": "",
        "step": state.step + 1,  # 账面步号 = 圈号（0928 定稿）
    }

    # 步骤 1：要一版（含插话循环）；拆解耗尽重试时本局按 ERROR 收尾，不再上抛。
    result = _elicit(deps, state, meta)
    if result.termination is not None:
        if result.termination is Termination.ERROR:
            return {
                "termination": Termination.ERROR,
                "judge_reason": EXHAUSTED_REASON,
                "decompositions_used": result.used,
            }
        return {
            **stopped_updates(state, deps, "episode", "plan_episode", result.termination),
            "decompositions_used": result.used,
        }
    resp, note = result.response, result.note
    assert resp is not None

    return _adopt(deps, state, meta, resp.decomposition, result.used, note)


def _adopt(
    deps: EpisodeRuntime,
    state: EpisodeRunState,
    meta: dict[str, object],
    proposal: Decomposition,
    used: int,
    note: str,
) -> dict[str, Any]:
    """整版采纳后分配逻辑身份，记录修订与最终顺序。"""
    # 步骤 2：编 task_id 与版次，记结论，追加进表。
    tasks = _to_tasks(proposal, state.goal.task_id, len(state.tasks))
    version = max((entry.round for entry in state.tasks), default=0) + 1
    entries = [TaskEntry(entry_id=t.task_id, task=t, round=version) for t in tasks]
    table, order = apply_planning(state.tasks, entries, proposal, state.execution_order)
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.DECOMPOSE_VERDICT,
            meta=meta,
            tasks=tasks,
            planning=proposal,
            planning_round=used,
            execution_order=order,
            why=proposal.why,
            human_note=note,
        )
    )
    return {
        "tasks": table,
        "execution_order": order,
        "latest_planning": proposal,
        "judge_trigger": "no_pending" if not order else "normal",
        "decompositions_used": used,
    }


def _elicit(deps: EpisodeRuntime, state: EpisodeRunState, meta: dict[str, object]) -> Elicited:
    """重问由共享图调度；AI 重写次数不超过剩余拆解预算。"""

    def ask_brain(note: str, number: int) -> Elicited:
        return _ask_version(deps, state, meta, note, number)

    def ask_reviewer(result: Elicited, rounds: ReviewRound) -> ReviewMark:
        return _review_version(deps, state, meta, result, rounds)

    revision_budget = max(0, deps.budget.max_decompositions - state.decompositions_used - 1)
    result, note = elicit_with_review(
        ask_brain,
        ask_reviewer,
        max_agent_rounds=min(REVIEW_AI_INJECT_MAX_ROUNDS, revision_budget),
    )
    return result.model_copy(update={"note": note})


def _ask_version(
    deps: EpisodeRuntime, state: EpisodeRunState, meta: dict[str, object], note: str, number: int
) -> Elicited:
    """一次逻辑拆解只占一轮；预算耗尽时不再问脑或询问 reviewer。"""
    used = state.decompositions_used + number
    if used > deps.budget.max_decompositions:
        return Elicited(note=note, used=used - 1, termination=Termination.DECOMPOSITIONS_EXHAUSTED)
    try:
        req = _request(deps, state, note)
        resp = _ask(deps, meta, req)
    except MaxRetriesExceeded:
        return Elicited(note=note, used=used, termination=Termination.ERROR)
    except BudgetExhausted:
        return Elicited(note=note, used=used, termination=Termination.TIME_EXHAUSTED)
    return Elicited(response=resp, request=req, note=note, used=used)


def _review_version(
    deps: EpisodeRuntime,
    state: EpisodeRunState,
    meta: dict[str, object],
    result: Elicited,
    rounds: ReviewRound,
) -> ReviewMark:
    """仅实际拆出提案后亮表；机械终止返回内部结束标记，不额外产出询问账。"""
    if result.response is None:
        assert result.termination is not None
        return ReviewMark(answered=False, by="none", wait_s=0, round=rounds.number)
    assert result.request is not None
    return ask_inject(
        deps.reviewer,
        deps.trace,
        FromHarnessToReviewerInjectReq(
            prompt=f"本局目标拆成 {len(result.response.decomposition.tasks)} 个 task，看对不对",
            form=result.response.decomposition,
            form_kind="Decomposition",
            round=rounds.number,
            max_agent_rounds=rounds.max_agent_rounds,
            context=ReviewContext(
                layer="episode",
                run_id=state.run_id,
                episode_id=state.episode_id,
                brain_input=result.request,
                tasks=state.tasks,
                step=meta["step"],
                fail_streak=state.fail_streak,
            ),
        ),
        meta=meta,
        rounds=rounds,
    )


def _request(
    deps: EpisodeRuntime, state: EpisodeRunState, note: str
) -> FromHarnessToBrainToolDecomposeReq:
    """只装本轮素材；校验后绑定 state 的详情原列表，与判定共享只读输入。"""
    req = FromHarnessToBrainToolDecomposeReq(
        remaining_planning_rounds=deps.budget.max_decompositions - state.decompositions_used,
        execution_order=state.execution_order,
        goal=current_goal(state),
        observation=state.ep_ctx.observation,
        task_memories=state.ep_ctx.task_memories,
        task_table=state.tasks,
        episode_index=state.ep_ctx.episode_index,
        knowledge=current_knowledge(state),
        max_tasks=min(EPISODE_MAX_TASKS_PER_PLAN, deps.budget.episode_max_tasks - state.step),
        last_judge=state.last_judge,
        human_note=note,
    )
    req.task_memories = state.ep_ctx.task_memories
    return req


def _ask(
    deps: EpisodeRuntime, meta: dict[str, object], req: FromHarnessToBrainToolDecomposeReq
) -> FromHarnessToBrainToolDecomposeResp:
    """问一次 decomposer 并记 `decompose_call`；耗尽时记整条账 + `call_exhausted` 后上抛。"""
    try:
        resp = deps.decomposer.decompose(req)
    except BudgetExhausted as exc:
        if exc.calls:
            deps.trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.DECOMPOSE_CALL,
                    meta=meta,
                    calls=list(exc.calls),
                )
            )
        raise
    except MaxRetriesExceeded as exc:
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.DECOMPOSE_CALL, meta=meta, calls=list(exc.calls)
            )
        )
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.CALL_EXHAUSTED, meta=meta, link="decompose"
            )
        )
        raise
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(kind=TraceKind.DECOMPOSE_CALL, meta=meta, calls=resp.calls)
    )
    return resp


def _to_tasks(decomposition: Decomposition, goal_id: str, existing: int) -> list[Task]:
    """模型方言 → `Task`：身份按 `{goal_id}-t{n}` 编，`n` 接着表里已有的条数往下数。"""
    return [
        Task(
            task_id=f"{goal_id}-t{existing + offset + 1}",
            goal=planned.goal,
            success_criteria=planned.success_criteria,
            max_steps=planned.max_steps,
        )
        for offset, planned in enumerate(decomposition.tasks)
    ]


__all__ = ["plan_episode"]
