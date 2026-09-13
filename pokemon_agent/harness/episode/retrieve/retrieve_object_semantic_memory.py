"""`retrieve_object_semantic_memory`：查语义记忆（object：这张地图上互动过的事件），
文字化后交给 `decide/think_action`。

事件 → 文本的转换在 `pokemon_agent.prompts.object_render.render_object_events`（渲染是
prompt 层的事，本节点只决定"查什么、记什么账"）。**统计口径 = 事件条数**——渲染文本
一行一条事件，两者恒相等。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolQueryObjectEventsReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.tools.prompts.object_render import render_object_events

from ...deps import HarnessDeps
from ..episode_state import EpisodeRunState


def retrieve_object_semantic_memory(
    state: EpisodeRunState, runtime: Runtime[HarnessDeps]
) -> dict[str, Any]:
    """查这张地图上的 object 事件。**只改 `object_semantic_memory` 一处。**

    `obs.place` 为 None 时没有地图可过滤，按空事件处理（同 `build_scene_key` 的
    "场景未知不是异常"）。

    前置条件：`state.observation` 非空。
    后置条件：返回 `{"object_semantic_memory": <渲染后的文本>}`。
    """
    deps = runtime.context
    assert state.observation is not None, "retrieve_object_semantic_memory before judge"
    ep, step = state.episode_id, state.observation.step
    if state.observation.place is None:
        events: list = []
    else:
        events = deps.memory.query_object_events(
            FromHarnessToMemoryToolQueryObjectEventsReq(
                map_id=state.observation.place.map_id, before_step=step
            )
        ).events
    known = render_object_events(events)
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.RETRIEVE_NODE,
            episode_id=ep,
            step=step,
            read_kind="object",
            count=len(events),
            refs="",
        )
    )
    return {"object_semantic_memory": known}
