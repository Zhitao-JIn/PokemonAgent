"""`store_step_episode_memory`：把上一键（before → action → after）反思成一条 ActMemory，落库。

**不改状态字段，只落库记账。** 盖四样章：`episode_id` / `run_id` / `task_id`（大脑
不知道自己在哪）与 `before_frame` / `after_frame` 两张截图——两张图从覆盖式帧槽取
（`frames.frame_b64`）：本单元跑在 perceive 格里、`sense` 刚把新帧放进
after 位之后，那一刻槽里正好是"这一键之前"与"这一键之后"两帧，零盘 IO。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolReflectReq,
    FromHarnessToMemoryToolMemorizeRecord,
    FromHarnessToMemoryToolMemorizeReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)

from ..frames import frame_b64
from ..script_report import result_line
from ..task_runtime import TaskRuntime
from ..task_state import TaskState


def store_step_episode_memory(state: TaskState, runtime: Runtime[TaskRuntime]) -> dict[str, Any]:
    """反思这一步并落一条情景记忆。**不改状态字段，返回空增量。**

    before = `task_ctx.observation`、after = `after_observation`；上一圈没按键（首圈）时不写。
    上一动作是脚本时，`result` 写结果那一句（结局码 + 摘要或原因）、`dialog` 写报告顶层的
    对话行；按键动作两者分别为空串与空列表。
    """
    if state.action is None:
        return {}
    deps = runtime.context
    assert state.after_observation is not None, "sense 没有产出新帧"
    ep, before, action, after = (
        state.episode_id,
        state.task_ctx.observation,
        state.action,
        state.after_observation,
    )

    # 步骤 1：反思成一条情景记忆，盖 run_id 与前后两帧。
    # 脚本动作把结果写进 `result`（一次调用占一步，结局码 + 摘要或原因就是那一步的机械结局），
    # 对话原文进 `dialog`（报告顶层的按行列表；按键动作没有报告，落空列表）。
    script_result = result_line(state.last_report) if state.last_report is not None else ""
    script_dialog = list((state.last_report or {}).get("dialog") or [])
    entry = deps.reflector.reflect(
        FromHarnessToBrainToolReflectReq(
            before=before,
            action=action,
            after=after,
            episode_id=ep,
            step=before.step,
            result=script_result,
        )
    ).entry.model_copy(
        update={
            "run_id": state.run_id,
            "task_id": state.task.task_id,
            "before_frame": frame_b64(deps, ep, before.step),
            "after_frame": frame_b64(deps, ep, before.step + 1),
            "dialog": script_dialog,
        }
    )

    # 步骤 2：落库并记账。
    deps.memory.memorize(
        FromHarnessToMemoryToolMemorizeReq(
            records=[FromHarnessToMemoryToolMemorizeRecord(kind="act", payload=entry.model_dump())]
        )
    )
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.WRITE_ACT_MEMORY,
            meta={
                "source": "store_step_episode_memory",
                "episode_id": ep,
                "task_id": state.task.task_id,
                "step": state.step + 1,
            },
            entry=entry,
        )
    )
    return {}
