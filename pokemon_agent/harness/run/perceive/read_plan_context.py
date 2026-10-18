"""读取本 run 全部局与地图事实、过往 run 背景；三种读账分别留痕。"""

from __future__ import annotations

import time
from typing import Any

from langgraph.runtime import Runtime
from pydantic import TypeAdapter

from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolRecallReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.memory import EpisodeMemory, ObjectFactEvent, RunMemory

from ..run_state import PlanContext, RunState
from ..runtime import RunRuntime


def read_plan_context(state: RunState, runtime: Runtime[RunRuntime]) -> dict[str, Any]:
    """写本圈 plan_ctx；详情与背景均全取，不改变读口给出的执行顺序。"""
    details, objects = _read_details_and_objects(state, runtime)
    run_index = _read_run_index(state, runtime)
    return {"plan_ctx": PlanContext(details=details, objects=objects, run_index=run_index)}


def _read_details_and_objects(
    state: RunState, runtime: Runtime[RunRuntime]
) -> tuple[list[EpisodeMemory], list[ObjectFactEvent]]:
    """同一次 run_id 召回分出全部局详情与地图事实，各记原有读账。"""
    started_at = time.time()
    response = runtime.context.memory.recall(
        FromHarnessToMemoryToolRecallReq(query="", conditions={"run_id": state.run_id}, limit=10**6)
    )
    details = [
        EpisodeMemory(**item.payload, markdown=item.content)
        for item in response.items
        if item.kind == "episode"
    ]
    _record_read(
        state,
        runtime,
        TraceKind.READ_EPISODE_MEMORY,
        f"run_id={state.run_id}",
        [memory.episode_id for memory in details],
        started_at,
    )
    started_at = time.time()
    adapter = TypeAdapter(ObjectFactEvent)
    objects = [
        adapter.validate_python(item.payload) for item in response.items if item.kind == "object"
    ]
    _record_read(
        state,
        runtime,
        TraceKind.READ_OBJECT_MEMORY,
        f"run_id={state.run_id} map_id=None",
        [event.place.key for event in objects],
        started_at,
    )
    return details, objects


def _read_run_index(state: RunState, runtime: Runtime[RunRuntime]) -> list[RunMemory]:
    """跨目标读取过往 run 的背景，排除本 run，并记录查询与实际保留的 refs。"""
    started_at = time.time()
    response = runtime.context.memory.recall(
        FromHarnessToMemoryToolRecallReq(query="", conditions={"runs": "all"}, limit=10**6)
    )
    memories = [
        RunMemory(**item.payload, markdown=item.content)
        for item in response.items
        if item.kind == "run"
    ]
    run_index = [memory for memory in memories if memory.run_id != state.run_id]
    _record_read(
        state,
        runtime,
        TraceKind.READ_RUN_MEMORY,
        "runs=all",
        [memory.run_id for memory in run_index],
        started_at,
    )
    return run_index


def _record_read(
    state: RunState,
    runtime: Runtime[RunRuntime],
    kind: TraceKind,
    query: str,
    refs: list[str],
    started_at: float,
) -> None:
    """三本读账共用本格 meta，分别保留各自的查询、refs 与计时。"""
    runtime.context.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=kind,
            meta={
                "source": "run.perceive",
                "episode_id": state.run_id,
                "task_id": state.run_id,
                "step": state.step + 1,
            },
            query=query,
            refs=refs,
            started_at=started_at,
            ended_at=time.time(),
        )
    )


__all__ = ["read_plan_context"]
