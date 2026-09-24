"""`plan_episode`：任务表里还有 PENDING 就直通；没有了（首圈 / 链走完 / 上一个 task 定案失败、
剩余条目被放弃）就问 decomposer 要下一版任务链（人可插话，带话重问），追加进表。

`task_id` 由这里编：`{goal.task_id}-t{n}`，`n` 接着任务表已有条数往下数（被弃的也算，id 不复用）。
decomposer 只给内容，身份归 harness。

拆解耗尽重试时本格写 `termination = ERROR`，本局经图的分叉走 `episode_done` 收尾。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.brain import Task
from pokemon_agent.brain.interface import Decomposition
from pokemon_agent.config import EPISODE_MAX_TASKS_PER_PLAN
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolDecomposeReq,
    FromHarnessToBrainToolDecomposeResp,
    FromHarnessToReviewerInjectReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.harness.domain import EntryStatus, TaskEntry, Termination

from ..episode_runtime import EpisodeRuntime
from ..episode_state import EpisodeRunState, current_goal

EXHAUSTED_REASON = "拆解耗尽重试，没有 task 可派"
"""拆解耗尽时写进 `judge_reason` 的机械说明（本局以 `Termination.ERROR` 收尾）。"""


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
        "task_id": state.episode_id,
        "step": state.ep_ctx.observation.step,
    }

    # 步骤 1：要一版（含插话循环）；拆解耗尽重试时本局按 ERROR 收尾，不再上抛。
    try:
        resp, note = _elicit(deps, state, meta)
    except MaxRetriesExceeded:
        return {"termination": Termination.ERROR, "judge_reason": EXHAUSTED_REASON}

    # 步骤 2：编 task_id 与版次，记结论，追加进表。
    tasks = _to_tasks(resp.decomposition, state.goal.task_id, len(state.tasks))
    version = max((entry.round for entry in state.tasks), default=0) + 1
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.DECOMPOSE_VERDICT,
            meta=meta,
            tasks=tasks,
            why=resp.decomposition.why,
            input=resp.calls[-1].payload.get("prompt", ""),
            output=resp.calls[-1].payload.get("raw", ""),
            human_note=note,
        )
    )
    return {"tasks": [*state.tasks, *(TaskEntry(task=t, round=version) for t in tasks)]}


def _elicit(
    deps: EpisodeRuntime, state: EpisodeRunState, meta: dict[str, object]
) -> tuple[FromHarnessToBrainToolDecomposeResp, str]:
    """问 decomposer 要一版；人有意见就带着那句话重问，直到人没意见。返回 `(定稿, 定稿时的插话)`。

    失败：`_ask` 耗尽时的 `MaxRetriesExceeded` 原样上抛（账已由 `_ask` 记好）。
    """
    note = ""
    while True:
        resp = _ask(
            deps,
            meta,
            FromHarnessToBrainToolDecomposeReq(
                goal=current_goal(state),
                observation=state.ep_ctx.observation,
                task_memories=state.ep_ctx.task_memories,
                task_table=state.tasks,
                episode_memories=state.ep_ctx.global_episode_memories,
                max_tasks=EPISODE_MAX_TASKS_PER_PLAN,
                human_note=note,
            ),
        )
        reply = deps.reviewer.inject(
            FromHarnessToReviewerInjectReq(
                prompt=f"本局目标拆成 {len(resp.decomposition.tasks)} 个 task，看对不对",
                form=resp.decomposition,
                form_kind="Decomposition",
            )
        )
        if not reply:
            return resp, note
        note = reply


def _ask(
    deps: EpisodeRuntime, meta: dict[str, object], req: FromHarnessToBrainToolDecomposeReq
) -> FromHarnessToBrainToolDecomposeResp:
    """问一次 decomposer 并记 `decompose_call`；耗尽时记整条账 + `call_exhausted` 后上抛。"""
    try:
        resp = deps.decomposer.decompose(req)
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
