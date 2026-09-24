"""`sense`（episode 层）：**每圈**用完整档（带视觉）取一帧 → `ep_ctx.observation`。

记 `sense_call`（视觉调用）↔ `sense_frame`（取到的这一帧）。

episode 层唯一向世界取帧的地方。判定与拆解都读这一帧的文字化结果（`observation.render()`），
所以首次拆解与失败后的重拆看到的是同一档画面。步号 = `total_acts`（本局已按键数）。
这一帧不进帧槽：帧槽只服务 task 层 ActMemory 的前后两张图；`sense_frame` 账直接带这张图。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind

from ...sensing import perceive_once
from ..episode_runtime import EpisodeRuntime
from ..episode_state import EpisodeRunState

_SOURCE = "sense"


def sense(state: EpisodeRunState, runtime: Runtime[EpisodeRuntime]) -> dict[str, Any]:
    """取一帧（完整档），写进 `ep_ctx.observation`。"""
    deps = runtime.context
    episode_id, step = state.episode_id, state.total_acts

    # 步骤 1：取帧，步号由本层盖。
    obs, frame_png = perceive_once(
        deps, episode_id=episode_id, task_id=episode_id, step=step, source=_SOURCE, ram_only=False
    )

    # 步骤 2：记观察账。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.SENSE_FRAME,
            meta={"source": _SOURCE, "episode_id": episode_id, "task_id": episode_id, "step": step},
            obs=obs,
            frame=frame_png,
        )
    )
    return {"ep_ctx": state.ep_ctx.model_copy(update={"observation": obs})}


__all__ = ["sense"]
