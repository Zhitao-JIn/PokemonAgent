"""`close_step`：把这一步**关上**——当前帧前进到刚感知的那一帧、步号加一。

改 `observation`/`step` 两处（"一步结束了"这一个判定的两面），并落一条 `STEP_ADVANCE`。

**扶正为什么并进这一格、又为什么排在这里**：`observation := pending_observation` 是
"这一步"的终点，不是"下一步"的起点；而它必须发生在两个 store **之后**——那两格要
`before`（`observation`）与 `after`（`pending_observation`）两帧同时在场，谁先扶正都会把
`before` 冲掉。而 stores 之后紧接着的就是"这一步结束了"这个分叉（回 `act` 按下一键，
还是回链首重新决策）——扶正与它是同一时刻的两面，所以并在这里，条件边也挂在这里
（`PLAN_graph_readability.md` §3.4）。

链内小循环每一步都经过它（`act → … → store_object_semantic_memory → close_step → act`）；
链尾那一次扶正之后回 `open/save_checkpoint`，下一个拿到 `observation` 的就是链首的
`open/record_observation`。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind

from ...deps import HarnessDeps
from ..episode_state import EpisodeRunState


def close_step(state: EpisodeRunState, runtime: Runtime[HarnessDeps]) -> dict[str, Any]:
    """扶正当前帧、步号加一，记一条 `STEP_ADVANCE`。**只改 `observation`/`step` 两处。**

    不变式：`observation.step == step`——`perceive_after_action` 已经把
    `pending_observation.step` 盖成 `before.step + 1`（与本格算出的步号同值）。两处不同值
    的话 `(episode_id, step)` 这个记忆键会从第二步起就错位。

    前置条件：`state.pending_observation` 非空（本圈一定经过 `perceive_after_action`）。
    后置条件：返回 `{"observation": …, "step": …}`。
    """
    deps = runtime.context
    assert state.pending_observation is not None, "close_step before any observation exists"
    # 步数推进也要留痕——"这一步关上"本身要有痕迹。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.STEP_ADVANCE,
            episode_id=state.episode_id,
            step=state.step,
            next_step=state.step + 1,
        )
    )
    return {"observation": state.pending_observation, "step": state.step + 1}
