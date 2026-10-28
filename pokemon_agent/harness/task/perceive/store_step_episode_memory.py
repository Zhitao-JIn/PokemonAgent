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
from pokemon_agent.schemas.memory import ActMemory

from ..frames import frame_b64
from ..task_runtime import TaskRuntime
from ..task_state import TaskState


def store_step_episode_memory(state: TaskState, runtime: Runtime[TaskRuntime]) -> dict[str, Any]:
    """反思这一步并落一条情景记忆。**不改状态字段，返回空增量。**

    before = `task_ctx.observation`、after = `after_observation`；上一圈没按键（首圈）时不写。
    上一动作是脚本时写入结构化结局与逐键观察；按键动作分别为空与空列表。
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
    entry = deps.reflector.reflect(
        FromHarnessToBrainToolReflectReq(
            before=before,
            action=action,
            after=after,
            episode_id=ep,
            step=before.step,
            outcome=state.last_outcome,
            observations=state.last_observations,
            before_ram=state.task_ctx.ram,
            after_ram=state.after_ram,
        )
    ).entry.model_copy(
        update={
            "run_id": state.run_id,
            "task_id": state.task.task_id,
            "before_frame": frame_b64(deps, ep, before.step),
            "after_frame": frame_b64(deps, ep, before.step + 1),
        }
    )

    # 步骤 2：落库并记账。
    _write_entry(deps, state, entry)
    return {}


def _write_entry(deps: TaskRuntime, state: TaskState, entry: ActMemory) -> None:
    """保存一条动作记忆并写同一条账。"""
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
                "episode_id": state.episode_id,
                "task_id": state.task.task_id,
                "step": state.step + 1,
            },
            entry=entry,
        )
    )
