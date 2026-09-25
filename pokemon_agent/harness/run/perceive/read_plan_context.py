"""`read_plan_context`：读本 run 的局索引（按执行序）、详情预取与地图事实，写 `plan_ctx`。

感知源是**记忆**（run 层没有世界帧）；零模型调用。
两路读各记一笔 `read_episode_memory` / `read_object_memory`。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolQueryEpisodeSummariesReq,
    FromHarnessToMemoryToolQueryObjectEventsReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.memory import EpisodeMemory

from ..run_state import PlanContext, RunState
from ..runtime import RunRuntime


def read_plan_context(state: RunState, runtime: Runtime[RunRuntime]) -> dict[str, Any]:
    """装配这一圈的规划与判定素材，写 `plan_ctx` 一处。"""
    deps = runtime.context
    meta = {
        "source": "run.perceive",
        "episode_id": state.run_id,
        "task_id": state.run_id,
        "step": state.step,
    }

    # 步骤 1：局索引（记忆按 `episode_id` 自然序返回，即执行序）+ 详情预取。
    index = deps.memory.query_episode_summaries(
        FromHarnessToMemoryToolQueryEpisodeSummariesReq(
            conditions={"run_id": state.run_id}, order_by="episode_id"
        )
    ).summaries
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.READ_EPISODE_MEMORY,
            meta=meta,
            query=f"run_id={state.run_id} order_by=episode_id",
            refs=[m.episode_id for m in index],
        )
    )

    # 步骤 2：本 run 的地图交互事实（run 级不按地图筛）。
    objects = deps.memory.query_object_events(
        FromHarnessToMemoryToolQueryObjectEventsReq(run_id=state.run_id)
    ).events
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.READ_OBJECT_MEMORY,
            meta=meta,
            query=f"run_id={state.run_id} map_id=None",
            refs=[f"({e.episode_id}, {e.step}, {e.place.key})" for e in objects],
        )
    )
    return {"plan_ctx": PlanContext(index=index, details=_pick_details(index), objects=objects)}


def _pick_details(index: list[EpisodeMemory]) -> list[EpisodeMemory]:
    """一期详情预取规则：**最近 1 局 + 全部失败局**。

    这是渐进披露的最小可用形态——上下文里装"全部局的骨架 + 少数几局的肉"，
    而不是"把所有局的正文都倒进去"。三条依据：

    - **最近 1 局**：刚发生的事最相关，模型规划下一步时最先要看它；
    - **全部失败局**：失败是最该被看见的原料，"这个做法不行"必须能传到下一版规划里；
    - 其余（更早的成功局）：只给索引行——它们的内容多半已经被后续局覆盖。

    二期上工具环（模型自己请求要哪几局的正文）之后，这个函数退休，
    `details` 由模型的请求决定（信封不用改）。
    """
    chosen = {memory.episode_id for memory in index if not memory.success}
    if index:
        chosen.add(index[-1].episode_id)
    return [memory for memory in index if memory.episode_id in chosen]


__all__ = ["read_plan_context"]
