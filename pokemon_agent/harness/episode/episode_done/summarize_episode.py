"""`summarize_episode`：本局 TaskMemory（带正/负标）→ 一条 EpisodeMemory；写 `reason`/`memory`。

`reason` 只在这里由 LLM 产出（`EpisodeSummary.reason`）。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolSummarizeReq,
    FromHarnessToMemoryToolStoreEpisodeSummaryReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)

from ..episode_runtime import EpisodeRuntime
from ..episode_state import EpisodeRunState


def summarize_episode(state: EpisodeRunState, runtime: Runtime[EpisodeRuntime]) -> dict[str, Any]:
    """问 summarizer → 落 EpisodeMemory → 返回 `{"reason", "memory"}`。

    前置条件：`done`、`termination` 非空、`task_memories` 非空。
    """
    assert state.done and state.termination is not None, (
        "summarize_episode before the episode finished"
    )
    assert state.ep_ctx.task_memories, "summarize_episode 不该在没有 task 记忆时被调到"
    deps = runtime.context
    meta = {
        "source": "summarize_episode",
        "episode_id": state.episode_id,
        "task_id": state.episode_id,
        "step": state.ep_ctx.observation.step,
    }
    req = FromHarnessToBrainToolSummarizeReq(
        entries=state.ep_ctx.task_memories,
        verdicts=state.task_verdicts,
        episode_id=state.episode_id,
        run_id=state.run_id,
        goal=state.goal.goal,
        termination=state.termination,
        judge_reason=state.judge_reason,
        steps=state.step,
        acts_used=state.total_acts,
        max_steps=state.goal.max_steps,
    )

    # 步骤 1：蒸馏；耗尽时记整条账 + call_exhausted 后上抛。
    try:
        result = deps.summarizer.summarize(req)
    except MaxRetriesExceeded as exc:
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.SUMMARIZE_EPISODE_CALL, meta=meta, calls=list(exc.calls)
            )
        )
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.CALL_EXHAUSTED, meta=meta, link="summarize_episode"
            )
        )
        raise
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.SUMMARIZE_EPISODE_CALL, meta=meta, calls=result.calls
        )
    )

    # 步骤 2：落库记账，交出 reason 与记忆。
    stored = deps.memory.store_episode_summary(
        FromHarnessToMemoryToolStoreEpisodeSummaryReq(memory=result.episode_memory)
    ).memory
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.WRITE_EPISODE_MEMORY, meta=meta, memory=stored
        )
    )
    return {"reason": result.summary.reason, "memory": stored}


__all__ = ["summarize_episode"]
