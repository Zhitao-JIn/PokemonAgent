"""`leave_chapter`：保证 **"一局恰好一条 EpisodeMemory"**。

这一局没有正文可蒸时补一张只有来源章的空章。

两个写点，**都在 episode 这一层的边上**：

- `episode_done` 里的 `leave_chapter` 单元：局正常收尾、但没有任何 TaskMemory 可蒸；
- run 层 `act` 接住整局异常时（episode 图已经死了，只能由接住它的人代写）。

先查再写：已有记录一个字都不动。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolQueryEpisodeSummariesReq,
    FromHarnessToMemoryToolStoreEpisodeSummaryReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.harness.domain import Termination
from pokemon_agent.schemas.memory import EpisodeMemory

from ..episode_runtime import EpisodeRuntime
from ..episode_state import EpisodeRunState

CHAPTER_RATIONALE = "本局没有产出可蒸馏的正文（整局异常，或收尾时没有一条 task 记忆）"
"""空章写进 `quality_rationale` 的那句话——它是这一条唯一说得出的内容。"""


def store_empty_chapter(
    deps: EpisodeRuntime,
    *,
    run_id: str,
    episode_id: str,
    goal: str,
    tasks_used: int,
    acts_used: int,
    termination: Termination,
    reason: str,
    source: str,
    step: int,
) -> EpisodeMemory:
    """这一局在记忆里还没有记录就补一张空章（记 `write_episode_memory`），返回那条记录。"""
    assert episode_id, "store_empty_chapter() needs a non-empty episode_id"
    existing = deps.memory.query_episode_summaries(
        FromHarnessToMemoryToolQueryEpisodeSummariesReq(conditions={"episode_id": episode_id})
    ).summaries
    if existing:
        return existing[0]
    chapter = EpisodeMemory(
        episode_id=episode_id,
        run_id=run_id,
        goal=goal,
        steps=tasks_used,
        acts_used=acts_used,
        termination=termination.value,
        reason=reason,
        summary="",
        quality_score=0.0,
        quality_rationale=CHAPTER_RATIONALE,
    )
    stored = deps.memory.store_episode_summary(
        FromHarnessToMemoryToolStoreEpisodeSummaryReq(memory=chapter)
    ).memory
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.WRITE_EPISODE_MEMORY,
            meta={"source": source, "episode_id": episode_id, "task_id": episode_id, "step": step},
            memory=stored,
        )
    )
    return stored


def leave_chapter(state: EpisodeRunState, runtime: Runtime[EpisodeRuntime]) -> dict[str, Any]:
    """没有 TaskMemory 可蒸时补空章，返回 `{"memory"}`。前置条件：`done`、`termination` 非空。"""
    assert state.done and state.termination is not None, "leave_chapter before the episode finished"
    stored = store_empty_chapter(
        runtime.context,
        run_id=state.run_id,
        episode_id=state.episode_id,
        goal=state.goal.goal,
        tasks_used=state.step,
        acts_used=state.total_acts,
        termination=state.termination,
        reason=state.reason,
        source="leave_chapter",
        step=state.ep_ctx.observation.step,
    )
    return {"memory": stored}


__all__ = ["CHAPTER_RATIONALE", "leave_chapter", "store_empty_chapter"]
