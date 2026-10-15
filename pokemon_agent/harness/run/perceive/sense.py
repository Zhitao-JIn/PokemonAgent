"""`sense`（run 层）：**每圈**用内存观测取一帧 → `observation`。

只记 `sense_frame`（取到的这一帧），不产出模型调用账。

run 层唯一向世界取帧的地方。取到的是**局与局之间**的世界状态：首圈 = 世界起点
载入后的画面，之后 = 上一局打完、还没派下一局的画面。消费方：`review_and_judge`
的机械判停读 `observation.done`（世界层自己的信号），不再借上一局结算带回的旧画面。

世界端口在 `RunRuntime.game` 上（与 `EpisodeRuntime.game` 同一实例，0928 起不再
经 episode 穿透），`RunRuntime` 满足 `_SensingDeps`（game + trace）这条最小协议。

两个步号分家（0928 定稿）：**帧观测**盖全局累计键数 `total_acts`（跨局累加——
局外帧没有「局内键数」的语义，盖它回答的是"这是全局第几个键之后的世界"）；
**账面步号** = `step + 1`（圈号，与 episode/task 两层同构）。
这一帧不进帧槽：帧槽只服务 task 层 ActMemory 的前后两张图；`sense_frame` 账直接带图。

"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind

from ...sensing import perceive_task
from ..run_state import RunState
from ..runtime import RunRuntime

_SOURCE = "run.sense"


def sense(state: RunState, runtime: Runtime[RunRuntime]) -> dict[str, Any]:
    """取一帧（内存观测），写进 `observation`。"""
    deps = runtime.context
    frame_step, account_step = state.total_acts, state.step + 1

    # 步骤 1：取帧；帧观测盖全局累计键数、观察账盖圈号。
    obs, frame_png, ram = perceive_task(deps, step=frame_step)

    # 步骤 2：记观察账（账面步号 = 圈号；run 级账的 episode_id / task_id 位都放 run_id）。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.SENSE_FRAME,
            meta={
                "source": _SOURCE,
                "episode_id": state.run_id,
                "task_id": state.run_id,
                "step": account_step,
            },
            obs=obs,
            frame=frame_png,
            ram=ram,
        )
    )
    return {"observation": obs}


__all__ = ["sense"]
