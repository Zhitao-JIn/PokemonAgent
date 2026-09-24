"""`summarize_task`：把本 task 的 ActMemory（带正/负标）蒸成一条 TaskMemory，写 `reason`。

`reason` 只在这里由 LLM 产出（`EpisodeSummary.reason`，进 `TaskMemory.reason`）。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolSummarizeTaskReq,
    FromHarnessToMemoryToolStoreTaskMemoryReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)

from ..task_runtime import TaskRuntime
from ..task_state import TaskState


def summarize_task(state: TaskState, runtime: Runtime[TaskRuntime]) -> dict[str, Any]:
    """问 task_summarizer → 落 TaskMemory → 返回 `{"reason": …}`。

    前置条件：`done`、`termination` 非空、`act_memories` 非空。
    """
    assert state.done and state.termination is not None, "summarize_task before the task finished"
    assert state.task_ctx.act_memories, "summarize_task 不该在没有 ActMemory 时被调到"
    deps = runtime.context
    meta = {
        "source": "summarize_task",
        "episode_id": state.episode_id,
        "task_id": state.task.task_id,
        "step": state.task_ctx.observation.step,
    }
    req = FromHarnessToBrainToolSummarizeTaskReq(
        entries=state.task_ctx.act_memories,
        verdicts=state.act_verdicts,
        task_id=state.task.task_id,
        episode_id=state.episode_id,
        run_id=state.run_id,
        goal=state.task.goal,
        termination=state.termination,
        judge_reason=state.judge_reason,
        steps_used=state.step,
        max_steps=state.task.max_steps,
    )

    # 步骤 1：蒸馏；耗尽时记整条账 + call_exhausted 后上抛。
    try:
        distilled = deps.task_summarizer.summarize_task(req)
    except MaxRetriesExceeded as exc:
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.SUMMARIZE_TASK_CALL, meta=meta, calls=list(exc.calls)
            )
        )
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.CALL_EXHAUSTED, meta=meta, link="summarize_task"
            )
        )
        raise
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.SUMMARIZE_TASK_CALL, meta=meta, calls=distilled.calls
        )
    )

    # 步骤 2：落库记账，交出 reason。
    deps.memory.store_task_memory(
        FromHarnessToMemoryToolStoreTaskMemoryReq(memory=distilled.memory)
    )
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.WRITE_TASK_MEMORY, meta=meta, memory=distilled.memory
        )
    )
    return {"reason": distilled.memory.reason, "memory": distilled.memory}


__all__ = ["summarize_task"]
