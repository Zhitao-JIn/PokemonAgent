"""`sense`（task 层）：**每圈**取一帧（带场合） → `after_observation`，记 `sense_frame`，落帧槽。

task 层唯一向世界取帧的地方。第一圈（还没按键）取的就是这个 task 的开局帧；之后每圈
取的是上一键之后的新帧。观测的 `step` = `total_acts + step`（局内累计键数，帧槽 / ActMemory
键控用）；**账面步号** = `step + 1`（圈号：dispatch 落 0、每圈取帧 +1，同圈所有账共用）。
后面的单元：上一圈按过键才写 ActMemory / 判停摆 / 记物件；`close_step` 每圈都把新帧转正。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind

from ...sensing import perceive_task
from ..frames import remember_frame
from ..task_runtime import TaskRuntime
from ..task_state import TaskState

_SOURCE = "task.sense"


def sense(state: TaskState, runtime: Runtime[TaskRuntime]) -> dict[str, Any]:
    """取一帧（只读内存与屏幕缓冲，带场合），写观察与同帧 RAM。"""
    deps = runtime.context
    episode_id, task_id = state.episode_id, state.task.task_id
    # 观测的 step 是局内累计键数（帧槽 / ActMemory 的键控来源）；账面步号另盖：
    # 圈号 = step + 1（dispatch 落 0、每圈取帧 +1，同圈所有账共用，0928 定稿）。
    obs_step = state.total_acts + state.step

    # 步骤 1：取帧，观测盖局内累计键数。
    obs, frame_png, ram = perceive_task(deps, step=obs_step)

    # 步骤 2：记观察账、落帧槽（ActMemory 的两张图从帧槽取）。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.SENSE_FRAME,
            meta={
                "source": _SOURCE,
                "episode_id": episode_id,
                "task_id": task_id,
                "step": state.step + 1,
            },
            obs=obs,
            frame=frame_png,
            ram=ram,
        )
    )
    remember_frame(deps, episode_id, obs_step, frame_png)
    return {"after_observation": obs, "after_ram": ram}


__all__ = ["sense"]
