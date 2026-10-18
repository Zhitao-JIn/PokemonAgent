"""run 层每圈检索知识，保留前一单元装好的全部 plan_ctx 其它字段。"""

from __future__ import annotations

import time
from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.config import MEMORY_RECALL_LIMIT
from pokemon_agent.harness.knowledge_query import build_knowledge_query
from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolRecallReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)

from ..run_state import RunState
from ..runtime import RunRuntime


def retrieve_run_knowledge(state: RunState, runtime: Runtime[RunRuntime]) -> dict[str, Any]:
    """每圈召回知识并记账；调用方保证 sense 与 read_plan_context 已完成。

    前置条件：observation、plan_ctx 非空。后置条件：只更新 plan_ctx.knowledge。
    """
    assert state.observation is not None, "run knowledge before sense"
    assert state.plan_ctx is not None, "run knowledge before read_plan_context"
    query = build_knowledge_query(state.observation, state.run_goal.goal)
    started_at = time.time()
    response = runtime.context.memory.recall(
        FromHarnessToMemoryToolRecallReq(query=query, conditions={}, limit=MEMORY_RECALL_LIMIT)
    )
    items = [item for item in response.items if item.kind == "knowledge"]
    ended_at = time.time()
    runtime.context.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.READ_KNOWLEDGE,
            meta={
                "source": "run.retrieve_knowledge",
                "episode_id": state.run_id,
                "task_id": state.run_id,
                "step": state.step + 1,
            },
            query=query,
            refs=[item.payload.get("source", "") for item in items],
            started_at=started_at,
            ended_at=ended_at,
            timings={},
        )
    )
    return {
        "plan_ctx": state.plan_ctx.model_copy(
            update={"knowledge": [item.content for item in items]}
        )
    }
