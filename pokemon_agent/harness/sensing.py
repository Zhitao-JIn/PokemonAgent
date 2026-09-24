"""`perceive_once`：**向世界取一帧**的唯一入口，episode 与 task 两层的 `sense` 单元共用。

与 `compose.py` / `judging.py` 同级的共享层：只依赖 tools 门面与 schemas，不认识任何一层的 state。
重试循环在 `GameTools.perceive_with_retry()`；这里只负责记感知账——成功走返回值里的 `log`，
耗尽走异常携带的 `calls`。world 交出的 `Observation.step` 恒为占位的 0，步号由调用方盖。
"""

from __future__ import annotations

from typing import Protocol

from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind
from pokemon_agent.tools.interface import GameToolPort, TraceToolPort
from pokemon_agent.world import Observation


class _SensingDeps(Protocol):
    """两层 runtime 都满足的那一小块：能取帧、能记账。"""

    game: GameToolPort
    trace: TraceToolPort


def perceive_once(
    deps: _SensingDeps,
    *,
    episode_id: str,
    task_id: str,
    step: int,
    source: str,
    ram_only: bool,
) -> tuple[Observation, str | None]:
    """取一帧、记感知账，返回 `(盖好步号的 observation, 原始画面 base64)`。

    失败：重试耗尽时先记账、再原样抛 `MaxRetriesExceeded`。
    """
    meta = {"source": source, "episode_id": episode_id, "task_id": task_id, "step": step}
    try:
        resp, log = deps.game.perceive_with_retry(ram_only=ram_only)
    except MaxRetriesExceeded as exc:
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.SENSE_CALL, meta=meta, calls=list(exc.calls)
            )
        )
        raise
    if log:
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(kind=TraceKind.SENSE_CALL, meta=meta, calls=list(log))
        )
    return resp.observation.model_copy(update={"step": step}), resp.frame_png


__all__ = ["perceive_once"]
