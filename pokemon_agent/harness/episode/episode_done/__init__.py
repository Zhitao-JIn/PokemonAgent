"""`episode_done` 格（episode 层）：**标 → 蒸 → 结**。

    verify_task_memories → summarize_episode → close_episode
    （没有 TaskMemory 时）leave_chapter → close_episode

素材是 perceive 装好的 `ep_ctx.task_memories`（本格不查库）。没有 TaskMemory 时跳过标与蒸，
改补一张空章（`reason` 留空），保证一局恰好一条 EpisodeMemory；结算照出。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from ...compose import compose_units
from ..episode_runtime import EpisodeRuntime
from ..episode_state import EpisodeRunState
from .close_episode import close_episode
from .leave_chapter import leave_chapter
from .summarize_episode import summarize_episode
from .verify_task_memories import verify_task_memories


def episode_done(state: EpisodeRunState, runtime: Runtime[EpisodeRuntime]) -> dict[str, Any]:
    """按序跑收尾单元，返回全部增量的合并。"""
    updates: dict[str, Any] = {}
    current = state

    # 步骤 1：有记忆才标、才蒸；没有就补空章。
    if current.ep_ctx.task_memories:
        inc = compose_units(current, runtime, (verify_task_memories, summarize_episode))
    else:
        inc = leave_chapter(current, runtime)
    updates.update(inc)
    current = current.model_copy(update=inc)

    # 步骤 2：出结算。
    updates.update(close_episode(current, runtime))
    return updates


__all__ = ["episode_done"]
