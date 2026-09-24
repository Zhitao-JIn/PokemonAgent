"""`review_and_judge` 格（task 层）：**机械三类 + 问模型**，写 `termination`。

停没停、成没成都由 `termination` 推出（`Settled`）。

①机械：世界结束（`obs.done`）/ 停摆（`stall_count >= ACT_STALL_LIMIT`）/ 键预算尽
（`step >= task.max_steps`）。②模型：第 1 键之后每圈问"task 目标达成没有"，
判成即 `GOAL_DONE`，覆盖机械结论。第 0 键不问模型。判定只看**本 task** 的最近几键
（按 ActMemory 的 `task_id` 章筛），不混进同局前面 task 的键。`reason` 不在这里写。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.brain import Goal
from pokemon_agent.config import JUDGE_HISTORY_STEPS, ACT_STALL_LIMIT
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolJudgeReq,
)
from pokemon_agent.schemas.harness.domain import Termination

from ...judging import ask_judger, judge_reason, mechanical_termination, record_verdict
from ..task_runtime import TaskRuntime
from ..task_state import TaskState

_SOURCE = "task.review_and_judge"


def review_and_judge(state: TaskState, runtime: Runtime[TaskRuntime]) -> dict[str, Any]:
    """两段式判停，返回 `{"termination"}`。"""
    deps = runtime.context
    ep, task_id, step = state.episode_id, state.task.task_id, state.task_ctx.observation.step
    stalled = state.stall_count >= ACT_STALL_LIMIT

    # 步骤 1：机械三类；第 0 键不问模型。
    termination = mechanical_termination(
        world_ended=state.task_ctx.observation.done,
        stalled=stalled,
        exhausted=state.step >= state.task.max_steps,
    )
    verdict = None

    # 步骤 2：问模型"task 目标达成没有"，判成覆盖机械结论。
    if state.step > 0:
        history = state.task_ctx.act_memories[-JUDGE_HISTORY_STEPS:]
        goal = Goal(goal=state.task.goal, criteria=state.task.success_criteria)
        verdict = ask_judger(
            deps.judger,
            deps.trace,
            FromHarnessToBrainToolJudgeReq(goal=goal, history=history),
            source=_SOURCE,
            episode_id=ep,
            task_id=task_id,
            step=step,
        )
        if verdict.done:
            termination = Termination.GOAL_DONE

    # 步骤 3：记结论。
    reason_for_judge = judge_reason(termination, verdict, not_asked="第 0 键不问模型")
    record_verdict(
        deps.trace,
        source=_SOURCE,
        episode_id=ep,
        task_id=task_id,
        step=step,
        termination=termination,
        judge_reason=reason_for_judge,
        verdict=verdict,
    )
    return {"termination": termination, "judge_reason": reason_for_judge}


__all__ = ["review_and_judge"]
