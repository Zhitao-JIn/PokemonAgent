"""run 记忆落库格：先查本 run，已有记录保持原样。"""

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolMemorizeRecord,
    FromHarnessToMemoryToolMemorizeReq,
    FromHarnessToMemoryToolRecallReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)

from ..run_state import RunState
from ..runtime import RunRuntime


def store_run_memory(state: RunState, runtime: Runtime[RunRuntime]) -> dict[str, Any]:
    """前置条件：summarize_run 已写交接槽；后置条件：本 run 至多一条记忆。"""
    assert state.run_memory is not None, "store_run_memory needs a summarized chapter"
    deps = runtime.context
    recalled = deps.memory.recall(
        FromHarnessToMemoryToolRecallReq(conditions={"runs": "all"}, limit=10**6)
    )
    existing = any(
        item.kind == "run" and item.payload.get("run_id") == state.run_id for item in recalled.items
    )
    if existing:
        return {}
    deps.memory.memorize(
        FromHarnessToMemoryToolMemorizeReq(
            records=[
                FromHarnessToMemoryToolMemorizeRecord(
                    kind="run", payload=state.run_memory.model_dump()
                )
            ]
        )
    )
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.WRITE_RUN_MEMORY,
            meta={
                "source": "run.store_run_memory",
                "episode_id": state.run_id,
                "task_id": state.run_id,
                "step": state.step + 1,
            },
            memory=state.run_memory,
        )
    )
    return {}
