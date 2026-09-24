"""`verify_act_memories`：给本 task 区间的 ActMemory 逐条打正/负标，写 `act_verdicts`。

**只标不筛**：负样本同样交给蒸馏作参考（`act_memories` 原样保留）。
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

from ..task_runtime import TaskRuntime
from ..task_state import TaskState


def verify_act_memories(state: TaskState, runtime: Runtime[TaskRuntime]) -> dict[str, Any]:
    """问 verifier，记 `verify_call`；返回 `{"act_verdicts": …}`。前置条件：`act_memories` 非空。"""
    assert state.task_ctx.act_memories, "verify_act_memories 不该在没有 ActMemory 时被调到"
    deps = runtime.context
    meta = {
        "source": "verify_act_memories",
        "episode_id": state.episode_id,
        "task_id": state.task.task_id,
        "step": state.task_ctx.observation.step,
    }

    # 步骤 1：问 verifier；耗尽时记整条账 + call_exhausted 后上抛。
    try:
        result = deps.verifier.verify(
            FromHarnessToBrainToolVerifyReq(
                entries=state.task_ctx.act_memories, goal=state.task.goal, knowledge=""
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
    return {"act_verdicts": result.verdicts}


__all__ = ["verify_act_memories"]
