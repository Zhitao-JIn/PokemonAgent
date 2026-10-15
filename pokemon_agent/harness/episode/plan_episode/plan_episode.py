"""`plan_episode`：任务表里还有 PENDING 就直通；没有了（首圈 / 链走完 / 上一个 task 定案失败、
剩余条目被放弃）就问 decomposer 要下一版任务链（人可插话，带话重问），追加进表。

`task_id` 由这里编：`{goal.task_id}-t{n}`，`n` 接着任务表已有条数往下数（被弃的也算，id 不复用）。
decomposer 只给内容，身份归 harness。

拆解耗尽重试时本格写 `termination = ERROR`，本局经图的分叉走 `episode_done` 收尾。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.brain import Task
from pokemon_agent.brain.interface import Decomposition
from pokemon_agent.config import EPISODE_MAX_TASKS_PER_PLAN
from pokemon_agent.errors import BudgetExhausted, MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolDecomposeReq,
    FromHarnessToBrainToolDecomposeResp,
    FromHarnessToReviewerInjectReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.harness.domain import EntryStatus, TaskEntry, Termination

from ...budget_nodes import stopped_updates
from ...reviewing import ask_inject
from ..episode_runtime import EpisodeRuntime
from ..episode_state import EpisodeRunState, current_goal, current_knowledge

EXHAUSTED_REASON = "拆解耗尽重试，没有 task 可派"
"""拆解耗尽时写进 `judge_reason` 的机械说明（本局以 `Termination.ERROR` 收尾）。"""


@dataclass(frozen=True)
class Elicited:
    """一次逻辑拆解的结果与已用轮数；内部模型重试不增加轮数。"""

    response: FromHarnessToBrainToolDecomposeResp | None
    note: str
    used: int
    termination: Termination | None = None


def plan_episode(state: EpisodeRunState, runtime: Runtime[EpisodeRuntime]) -> dict[str, Any]:
    """还有 PENDING 返回空增量；否则把新一版追加进任务表（至少一条）。

    拆解耗尽重试（`MaxRetriesExceeded`）时不追加，返回 `{"termination": ERROR, "judge_reason"}`，
    图的分叉据此把本局送进 `episode_done` 正常收尾，而不是让异常冒到 run 层记 `episode_error`。
    """
    if any(entry.status is EntryStatus.PENDING for entry in state.tasks):
        return {}
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

    # 步骤 2：编 task_id 与版次，记结论，追加进表。
    tasks = _to_tasks(resp.decomposition, state.goal.task_id, len(state.tasks))
    version = max((entry.round for entry in state.tasks), default=0) + 1
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.DECOMPOSE_VERDICT,
            meta=meta,
            tasks=tasks,
            why=resp.decomposition.why,
            human_note=note,
        )
    )
    return {
        "tasks": [*state.tasks, *(TaskEntry(task=t, round=version) for t in tasks)],
        "decompositions_used": result.used,
    }


def _elicit(deps: EpisodeRuntime, state: EpisodeRunState, meta: dict[str, object]) -> Elicited:
    """人要求重拆也计轮数；返回定稿或机械终止，以及已用逻辑轮数。"""
    note = ""
    used = state.decompositions_used
    while True:
        if used >= deps.budget.max_decompositions:
            return Elicited(None, note, used, Termination.DECOMPOSITIONS_EXHAUSTED)
        used += 1
        try:
            resp = _ask(deps, meta, _request(deps, state, note))
        except MaxRetriesExceeded:
            return Elicited(None, note, used, Termination.ERROR)
        except BudgetExhausted:
            return Elicited(None, note, used, Termination.TIME_EXHAUSTED)
        reply = ask_inject(
            deps.reviewer,
            deps.trace,
            FromHarnessToReviewerInjectReq(
                prompt=f"本局目标拆成 {len(resp.decomposition.tasks)} 个 task，看对不对",
                form=resp.decomposition,
                form_kind="Decomposition",
            ),
            meta=meta,
        )
        if not reply:
            return Elicited(resp, note, used)
        note = reply


def _request(
    deps: EpisodeRuntime, state: EpisodeRunState, note: str
) -> FromHarnessToBrainToolDecomposeReq:
    """只装本轮素材，模型重试仍由门面负责。"""
    return FromHarnessToBrainToolDecomposeReq(
        goal=current_goal(state),
        observation=state.ep_ctx.observation,
        task_memories=state.ep_ctx.task_memories,
        task_table=state.tasks,
        episode_memories=state.ep_ctx.global_episode_memories,
        knowledge=current_knowledge(state),
        max_tasks=min(EPISODE_MAX_TASKS_PER_PLAN, deps.budget.episode_max_tasks - state.step),
        last_judge=state.last_judge,
        human_note=note,
    )


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
