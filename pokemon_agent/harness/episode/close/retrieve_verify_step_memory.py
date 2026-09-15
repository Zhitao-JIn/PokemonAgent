"""`retrieve_verify_step_memory`：查本局全部 step 记忆，交给收尾链的判定器。

**图上单独一格，只改 `verify_step_entries` 一处**——跟主循环的
`retrieve/step_episode_memory` 是同一个 level：查库单独成节点，不跟判定逻辑缝在一起。

只在判完成的收尾分支上跑一次（不是每步）。没有 step 记忆时留空列表——下游路由据此
直接结束这一局的收尾链（跳过校验）。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolQueryEpisodeStepsReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)

from ...deps import HarnessDeps
from ..episode_state import EpisodeRunState


def retrieve_verify_step_memory(
    state: EpisodeRunState, runtime: Runtime[HarnessDeps]
) -> dict[str, Any]:
    """查本局全部 step 记忆。**只改 `verify_step_entries` 一处。**

    这个节点只在收尾链跑一次，但也要留自己的痕迹——entries 为空（下游跳 verify 直接
    蒸馏）时这条正好说明"查了，没有可校验的 step 记忆"。

    前置条件：`state.observation` 非空且 `state.done`（本局已判完成）。
    后置条件：返回 `{"verify_step_entries": …}`，并记一条 `read_verify_step`
    （与主循环那条 `read_step` 同形：同一个条件、同一种清单）。
    """
    deps = runtime.context
    assert state.observation is not None and state.done, (
        "retrieve_verify_step_memory before the episode finished"
    )
    ep, step = state.episode_id, state.observation.step
    entries = deps.memory.query_episode_steps(
        FromHarnessToMemoryToolQueryEpisodeStepsReq(episode_id=ep)
    ).steps
    refs = [f"({m.episode_id}, {m.step})" for m in entries]
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.READ_VERIFY_STEP,
            meta={"source": "retrieve_verify_step_memory", "episode_id": ep, "step": step},
            query=f"episode_id={ep}",
            refs=refs,
        )
    )
    return {"verify_step_entries": entries}
