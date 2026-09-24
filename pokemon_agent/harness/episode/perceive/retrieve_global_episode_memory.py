"""`retrieve_global_episode_memory`——按 run 取回本 run 已沉淀的跨局摘要。

**取法是"按元数据过滤"，不是"按相关性检索"**（0914 定案）：`MemoryTool` 的读口
现在只认 `conditions`（等值交集），场景匹配、相关性排序、条数截断全归消费方。
本格目前只做最保守的那一种取法——**限本 run 全取**。一条 `episode_memory` 是
**某一局 step 记忆的总结**，本格要的正是"**本 run 早先那几局**发生过什么"；别的 run
沉淀的摘要讲的是别的局面，把它当成本 run 的经历用，就会把失败局蒸馏出的"已验证"
当真（取舍见 `CHANGELOG.md` 2026-09-03 条目）。**这是调用方自己的安全阀，不是读口的
规则**——读口只认 `conditions`、根本不解释 run，限不限由每个消费方自己决定；
run 级规划（`plan`）读的同样是**本 run** 的摘要。

**不再按场景过滤**：原先本文件里那套 `build_scene_key`（拼 `map:/scene:/overlay:`
键 → `EpisodeMemory.matches_scene` 通配匹配）已随"读口不做领域规则"一起删除；
`obs.place` 为 None 的早退分支也随之消失——没有场景要拼了。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolQueryEpisodeSummariesReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)

from ..episode_runtime import EpisodeRuntime
from ..episode_state import EpisodeRunState


def retrieve_global_episode_memory(
    state: EpisodeRunState, runtime: Runtime[EpisodeRuntime]
) -> dict[str, Any]:
    """查本 run 沉淀的跨局摘要（等值筛 `run_id`，全量取回）。
    **只改 `ep_ctx.global_episode_memories` 一处。**

    前置条件：`state.ep_ctx` 非空。
    后置条件：返回 `{"global_episode_memories": …}`，并记一条 `read_episode_memory`
    （**空清单**与"没查"是两回事）。
    """
    deps = runtime.context
    ep, step = state.episode_id, state.ep_ctx.observation.step
    episode_memories = deps.memory.query_episode_summaries(
        FromHarnessToMemoryToolQueryEpisodeSummariesReq(conditions={"run_id": state.run_id})
    ).summaries
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.READ_EPISODE_MEMORY,
            meta={
                "source": "retrieve_global_episode_memory",
                "episode_id": ep,
                "task_id": ep,
                "step": step,
            },
            # 检索条件就是那条 `conditions`（本格唯一的一个等值项）。
            query=f"run_id={state.run_id}",
            refs=[m.episode_id for m in episode_memories],
        )
    )
    return {"ep_ctx": state.ep_ctx.model_copy(update={"global_episode_memories": episode_memories})}
