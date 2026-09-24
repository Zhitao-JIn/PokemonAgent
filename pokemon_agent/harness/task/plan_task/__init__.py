"""`plan_task` 格（task 层）：**产键**——问 chooser 要这一键，写 `state.action`。

素材：RAM 档观测（含屏幕文字读出的对话 / 选项 / 光标）+ 受限动作空间 + 本 task 目标
+ 最近 8 条 ActMemory。**只产出单键**：取首段、`times` 恒为 1（prompt 同样要求单键）。

失败契约同 judge：重试耗尽落整条账 + `CALL_EXHAUSTED`（`link="choose"`）后原样上抛。
账：`choose_call`（MODEL_CALL）+ `choose_verdict`（LLM_OUTCOME）。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.brain import Action, Goal
from pokemon_agent.config import CHOOSE_HISTORY_STEPS
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolChooseOnceReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)

from ..task_runtime import TaskRuntime
from ..task_state import TaskState


def plan_task(state: TaskState, runtime: Runtime[TaskRuntime]) -> dict[str, Any]:
    """问 chooser 出本键，写 `state.action` 一处。

    前置条件：`state.task_ctx` 非空且 `task_ctx.action_space` 非空
        （`perceive` 刚抄过动作边界）、`done` 为假（判停路由保证）。
    后置条件：返回 `{"action": 单键动作}`。
    失败：重试耗尽时抛 `MaxRetriesExceeded`（`link="choose"`），先留整条账。
    """
    deps = runtime.context
    assert state.task_ctx is not None, "plan_task before perceive"
    assert state.task_ctx.action_space is not None, "plan_task without an action space"
    ep = state.episode_id
    step = state.start_step + state.step

    # ========== 1. 组装 req（本 task 的目标 + 轻感知帧 + 受限空间 + 近期记忆） ==========
    history = state.task_ctx.act_memories[-CHOOSE_HISTORY_STEPS:]
    req = FromHarnessToBrainToolChooseOnceReq(
        goals=[Goal(goal=state.task.goal, criteria=state.task.success_criteria)],
        obs=state.task_ctx.observation,
        space=state.task_ctx.action_space,
        memories=history,
    )

    # ========== 2. 问 chooser → 落账 → 取单键 ==========
    try:
        resp = deps.chooser.choose(req)
    except MaxRetriesExceeded as exc:
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.CHOOSE_CALL,
                meta={
                    "source": "plan_task",
                    "episode_id": ep,
                    "task_id": state.task.task_id,
                    "step": step,
                },
                calls=list(exc.calls),
            )
        )
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.CALL_EXHAUSTED,
                meta={
                    "source": "plan_task",
                    "episode_id": ep,
                    "task_id": state.task.task_id,
                    "step": step,
                },
                link="choose",
            )
        )
        raise
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.CHOOSE_CALL,
            meta={
                "source": "plan_task",
                "episode_id": ep,
                "task_id": state.task.task_id,
                "step": step,
            },
            calls=resp.calls,
        )
    )

    # ========== 3. 单键化：取首段（thought 沿用），写 THINK ==========
    head = resp.action.sequence[0].model_copy(update={"times": 1})
    action = Action(thought=resp.action.thought, sequence=[head])
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.CHOOSE_VERDICT,
            meta={
                "source": "plan_task",
                "episode_id": ep,
                "task_id": state.task.task_id,
                "step": step,
            },
            action=action,
            input=resp.calls[-1].payload.get("prompt", ""),
            output=resp.calls[-1].payload.get("raw", ""),
        )
    )
    return {"action": action}


__all__ = ["plan_task"]
