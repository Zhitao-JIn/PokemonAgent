"""`sense`（task 层）：**每圈**用 RAM 档取一帧 → `after_observation`，记 `sense_frame`，落帧槽。

task 层唯一向世界取帧的地方。第一圈（还没按键）取的就是这个 task 的开局帧；之后每圈
取的是上一键之后的新帧。步号 = `start_step + step`（全局键号的唯一来源）。
后面的单元：上一圈按过键才写 ActMemory / 判停摆 / 记物件；`close_step` 每圈都把新帧转正。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind

from ...sensing import perceive_once
from ..frames import remember_frame
from ..task_runtime import TaskRuntime
from ..task_state import TaskState

_SOURCE = "task.sense"


def sense(state: TaskState, runtime: Runtime[TaskRuntime]) -> dict[str, Any]:
    """取一帧（RAM 档），写 `after_observation`。"""
    deps = runtime.context
    episode_id, task_id = state.episode_id, state.task.task_id
    step = state.start_step + state.step

    # 步骤 1：取帧，步号由本层盖。
    obs, frame_png = perceive_once(
        deps, episode_id=episode_id, task_id=task_id, step=step, source=_SOURCE, ram_only=True
    )

    # 步骤 2：记观察账、落帧槽（ActMemory 的两张图从帧槽取）。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.SENSE_FRAME,
            meta={"source": _SOURCE, "episode_id": episode_id, "task_id": task_id, "step": step},
            obs=obs,
            frame=frame_png,
        )
    )
    remember_frame(deps, episode_id, step, frame_png)
    return {"after_observation": obs}


__all__ = ["sense"]
