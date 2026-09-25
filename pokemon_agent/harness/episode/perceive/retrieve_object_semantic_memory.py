"""`retrieve_object_semantic_memory`：查语义记忆（object：这张地图上互动过的事件），
文字化后交给 `plan_episode`。

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

from ..episode_runtime import EpisodeRuntime
from ..episode_state import EpisodeRunState


def retrieve_object_semantic_memory(
    state: EpisodeRunState, runtime: Runtime[EpisodeRuntime]
) -> dict[str, Any]:
    """查本 run 在这张地图上的 object 事件。**只改 `ep_ctx.object_semantic_memory` 一处。**

    `obs.place` 为 None 时没有地图可过滤，按空事件处理——一局刚开始、地形还没
    读出来是正常情形，不是异常。

    前置条件：`state.ep_ctx` 非空。
    后置条件：返回 `{"object_semantic_memory": <渲染后的文本>}`。
    """
    deps = runtime.context
    ep, step = state.episode_id, state.ep_ctx.observation.step
    place = state.ep_ctx.observation.place
    if place is None:
        events: list = []
    else:
        events = deps.memory.query_object_events(
            FromHarnessToMemoryToolQueryObjectEventsReq(
                run_id=state.run_id, map_id=place.map_id, before_step=step
            )
        ).events
    known = render_object_events(events)
    # `refs` 记每条事件的唯一键 `(episode_id, step, 物体格)`——物体格（`PlaceInWorld.key`，
    # 形如 `12:13:8`）单独不唯一：同一格反复互动会有多条，回放要按键取回确定的那几条。
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
                "task_id": ep,
                "step": step,
            },
            query=(
                f"run_id={state.run_id} map_id={place.map_id if place else None} before_step={step}"
            ),
            refs=[f"({e.episode_id}, {e.step}, {e.place.key})" for e in events],
        )
    )
    return {"ep_ctx": state.ep_ctx.model_copy(update={"object_semantic_memory": known})}
