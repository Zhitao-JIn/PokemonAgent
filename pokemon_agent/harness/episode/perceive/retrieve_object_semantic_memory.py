"""按地图与局内键号检索原始交互事件，保留 trace 引用和事件顺序。"""

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
from pokemon_agent.schemas.memory import ObjectFactEvent

from ..episode_runtime import EpisodeRuntime
from ..episode_state import EpisodeRunState


def retrieve_object_semantic_memory(
    state: EpisodeRunState, runtime: Runtime[EpisodeRuntime]
) -> dict[str, Any]:
    """前置：本圈观测已取；返回本圈 object_semantic_events，不渲染模型文案。"""
    deps = runtime.context
    ep, place = state.episode_id, state.ep_ctx.observation.place
    # 两个步号分家（0928 定稿）：object 事件按**局内累计键数**存坐标（与 ActMemory 同口径），
    # 查询条件 `before_step` 必须用键数；账面步号是**圈号**（episode_start 落 0、每圈 +1）。
    before_step, step = state.total_acts, state.step + 1
    t0 = time.time()
    if place is None:
        events: list[ObjectFactEvent] = []
    else:
        resp = deps.memory.recall(
            FromHarnessToMemoryToolRecallReq(
                query="",
                conditions={"run_id": state.run_id, "map_id": str(place.map_id)},
                limit=10**6,
            )
        )
        _adapter = TypeAdapter(ObjectFactEvent)
        events = [
            _adapter.validate_python(item.payload) for item in resp.items if item.kind == "object"
        ]
        if before_step is not None:
            events = [e for e in events if e.step < before_step]
    t1 = time.time()
    # `refs` 记每条事件的物体格（`PlaceInWorld.key`，形如 `12:13:8`）。
    #
    # `query` 照实记检索条件，`place` 为 None 时写 `map_id=None`——**这一格那时
    # 压根没查**（按空事件处理），"没查"与"查了没命中"在账上必须分得开：
    # 后者是"query 有 map_id、清单为空"，前者连条件都凑不出来。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.READ_OBJECT_MEMORY,
            meta={
                "source": "retrieve_object_semantic_memory",
                "episode_id": ep,
                "task_id": "",
                "step": step,
            },
            query=(
                f"run_id={state.run_id} map_id={place.map_id if place else None}"
                f" before_step={before_step}"
            ),
            refs=[e.place.key for e in events],
            started_at=t0,
            ended_at=t1,
        )
    )
    return {"ep_ctx": state.ep_ctx.model_copy(update={"object_semantic_events": events})}
