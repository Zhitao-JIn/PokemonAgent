"""`plan_task` 格（task 层）：**产键**——问 chooser 要这一键，写 `state.action`。

素材：RAM 档观测（含屏幕文字读出的对话 / 选项 / 光标）+ 受限动作空间 + 本 task 目标
+ 本 task 全部 ActMemory + 上一脚本结果。**只产出单键**：取首段、`times` 恒为 1
（prompt 同样要求单键）；选了脚本则产出一个脚本调用，原样交出。

失败契约同 judge：重试耗尽落整条账 + `CALL_EXHAUSTED`（`link="choose"`）后原样上抛。
账：`choose_call`（MODEL_CALL）+ `choose_verdict`（LLM_OUTCOME）。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.brain import Action, Goal
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    AuditVerdict,
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)

from ...planning_budgets import shared_budgets, task_budgets
from ..task_runtime import TaskRuntime
from ..task_state import TaskState


def plan_task(state: TaskState, runtime: Runtime[TaskRuntime]) -> dict[str, Any]:
    """选择一项动作并记调用/结论账；调用方保证perceive已装好观测和动作空间。

    失败时保留所有尝试账并抛MaxRetriesExceeded；成功返回一键或一个脚本。
    """
    deps = runtime.context
    assert state.task_ctx.observation is not None, "plan_task before perceive"
    assert state.task_ctx.action_space is not None, "plan_task without an action space"
    meta = {
        "source": "plan_task",
        "episode_id": state.episode_id,
        "task_id": state.task.task_id,
        "step": state.step + 1,
    }
    action = _choose(deps, _request(state, deps), meta)
    if action.script is None:
        action = Action(sequence=[action.sequence[0].model_copy(update={"times": 1})])
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(kind=TraceKind.CHOOSE_VERDICT, meta=meta, action=action)
    )
    return {"action": action}


def _request(state: TaskState, deps: TaskRuntime) -> FromHarnessToBrainToolChooseOnceReq:
    """转换当前素材并保留history原列表；配置与父级建议分别传递。"""
    history = state.task_ctx.act_memories
    req = FromHarnessToBrainToolChooseOnceReq(
        budget_context=task_budgets(
            deps.config.budget,
            advice=state.task.max_steps,
            actions=state.step,
        )
        + shared_budgets(
            deps.config.budget,
            action_limit=state.actions_budget,
            actions=state.step,
            remaining_s=state.remaining_s,
        ),
        goals=[Goal(goal=state.task.goal, criteria=state.task.success_criteria)],
        obs=state.task_ctx.observation,
        space=state.task_ctx.action_space,
        memories=history,
        task_index=state.task_index,
        last_outcome=state.last_outcome,
        knowledge="\n\n".join(state.knowledge),
        human_note=(
            state.last_judge.note
            if state.last_judge is not None and state.last_judge.audit is AuditVerdict.OVERTURN
            else ""
        ),
    )
    req.memories = history
    return req


def _choose(
    deps: TaskRuntime, req: FromHarnessToBrainToolChooseOnceReq, meta: dict[str, object]
) -> Action:
    """一次逻辑选择的全部调用先落盘；耗尽另记错误账再原样抛出。"""
    try:
        response = deps.chooser.choose(req)
    except MaxRetriesExceeded as exc:
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.CHOOSE_CALL, meta=meta, calls=list(exc.calls)
            )
        )
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(kind=TraceKind.CALL_EXHAUSTED, meta=meta, link="choose")
        )
        raise
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(kind=TraceKind.CHOOSE_CALL, meta=meta, calls=response.calls)
    )
    return response.action


__all__ = ["plan_task"]
