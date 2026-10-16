"""`sense`（episode 层）：**每圈**用内存观测取一帧 → `ep_ctx.observation`。

只记 `sense_frame`（取到的这一帧），不产出模型调用账。

episode 层唯一向世界取帧的地方。判定与拆解都读这一帧的文字化结果（`observation.render()`），
所以首次拆解与失败后的重拆看到的是同一档画面。两个步号分家（0928 定稿）：**帧观测**的
局内累计键数 = `total_acts`（帧槽 / 记忆坐标口径）；**账面步号** = `step + 1`（圈号，
episode_start 落 0、每圈 +1，同圈所有账共用）。
这一帧不进帧槽：帧槽只服务 task 层 ActMemory 的前后两张图；`sense_frame` 账直接带这张图。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind

from ...sensing import perceive_task
from ..episode_runtime import EpisodeRuntime
from ..episode_state import EpisodeRunState

_SOURCE = "sense"


def sense(state: EpisodeRunState, runtime: Runtime[EpisodeRuntime]) -> dict[str, Any]:
    """取一帧（内存观测），写进 `ep_ctx.observation`。"""
    deps = runtime.context
    episode_id = state.episode_id
    frame_step, account_step = state.total_acts, state.step + 1

    # 步骤 1：取帧；帧观测盖键数、观察账盖圈号。
    obs, frame_png, ram = perceive_task(deps, step=frame_step)

    # 步骤 2：记观察账（账面步号 = 圈号）。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.SENSE_FRAME,
            meta={"source": _SOURCE, "episode_id": episode_id, "task_id": "", "step": account_step},
            obs=obs,
            frame=frame_png,
            ram=ram,
        )
    )
    return {"ep_ctx": state.ep_ctx.model_copy(update={"observation": obs})}


__all__ = ["sense"]
