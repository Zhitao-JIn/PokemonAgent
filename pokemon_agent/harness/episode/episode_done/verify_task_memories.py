"""`verify_task_memories`：给本局 TaskMemory 逐条打正/负标，写 `task_verdicts`。

**只标不筛**：负样本同样交给蒸馏作参考（`task_memories` 原样保留）。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolVerifyReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)

from ..episode_runtime import EpisodeRuntime
from ..episode_state import EpisodeRunState


def verify_task_memories(
    state: EpisodeRunState, runtime: Runtime[EpisodeRuntime]
) -> dict[str, Any]:
    """问 verifier，记 `verify_call`，返回 `{"task_verdicts": …}`。前置：`task_memories` 非空。"""
    assert state.ep_ctx.task_memories, "verify_task_memories 不该在没有 task 记忆时被调到"
    deps = runtime.context
    meta = {
        "source": "verify_task_memories",
        "episode_id": state.episode_id,
        "task_id": state.episode_id,
        "step": state.ep_ctx.observation.step,
    }

    # 步骤 1：问 verifier；耗尽时记整条账 + call_exhausted 后上抛。
    try:
        result = deps.verifier.verify(
            FromHarnessToBrainToolVerifyReq(
                entries=state.ep_ctx.task_memories,
                goal=state.goal.goal,
                knowledge=_knowledge_text(state),
            )
        )
    except MaxRetriesExceeded as exc:
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.VERIFY_CALL, meta=meta, calls=list(exc.calls)
            )
        )
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(kind=TraceKind.CALL_EXHAUSTED, meta=meta, link="verify")
        )
        raise

    # 步骤 2：记账，标注原样交出。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.VERIFY_CALL, meta=meta, calls=result.calls, verdicts=result.verdicts
        )
    )
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.VERIFY_VERDICT,
            meta=meta,
            checked=len(result.verdicts),
            negative=sum(1 for v in result.verdicts if not v.positive),
            input=result.calls[-1].payload.get("prompt", "") if result.calls else "",
            output=result.calls[-1].payload.get("raw", "") if result.calls else "",
        )
    )
    return {"task_verdicts": result.verdicts}


def _knowledge_text(state: EpisodeRunState) -> str:
    """本圈 perceive 检索到的领域知识，拼成 verify 的 `knowledge` 素材；没查到给空串。"""
    hit = state.ep_ctx.knowledge_semantic_memory
    return "\n\n".join(hit.contents) if hit is not None else ""


__all__ = ["verify_task_memories"]
