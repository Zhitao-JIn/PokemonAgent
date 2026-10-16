"""`perceive_task`：三层共享的内存观测取帧入口，不调用模型。

world 的 step 恒填 0 占位；调用方按本层累计动作数盖帧步号，另行记录账面圈号。
"""

from __future__ import annotations

from typing import Protocol

from pokemon_agent.direct.interface import GameToolPort, TraceToolPort
from pokemon_agent.world import RamReadout, TaskObservation


class _SensingDeps(Protocol):
    """三层 runtime 都满足的那一小块：能取帧、能记账。"""

    game: GameToolPort
    trace: TraceToolPort


def perceive_task(
    deps: _SensingDeps, *, step: int
) -> tuple[TaskObservation, str, RamReadout | None]:
    """取一帧（只读内存与屏幕缓冲），返回 `(盖好步号的 observation, 原始画面, 内存读数)`。"""
    resp = deps.game.perceive_task()
    return resp.observation.model_copy(update={"step": step}), resp.frame_png, resp.ram


__all__ = ["perceive_task"]
