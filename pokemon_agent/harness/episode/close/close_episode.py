"""`close_episode`：**本局收尾**——算结算写进 `state.outcome`，并落一条 `EPISODE_END`。

这是**第 21 个节点**（v1 想让它留在图外，见下）。收尾链的每一条分支都汇到这一格：
没有 step 记忆时从 `retrieve_verify_step_memory` 直接跳过来，有记忆时跟在
`verify_and_summarize` 后面。

**为什么它必须是图内的一个节点**（D2-④）：`outcome` 是父子图交界上的**输出键**——父侧
`RunState.outcome` 与它同名同型。而父子图按**键名交集**传递（F1）：子图不输出的键，父侧
**保持旧值且不报错**。所以"下结论"若留在图外（早先的 `EpisodeHarness._close` 就在图外），
`reflect` 读到的是**上一次派发的陈旧结算**——一个不炸的错。

它只算账：`done`/`success` 是 `gate/judge` 的产物，`obs.step` 是画面维度的坐标，
`stall_count` 是停摆护栏——本格一个都不改。

`derive_episode_reason` 跟着本节点（判据见 `PLAN_graph_composition.md` §3.5）。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.config import STALL_LIMIT
from pokemon_agent.schemas.harness import (
    FromHarnessToTraceToolAppendReq,
    FromRunHarnessToEpisodeHarnessRunResp,
    TraceKind,
)

from ...deps import HarnessDeps
from ..episode_state import EpisodeRunState


def derive_episode_reason(success: bool, step: int, max_steps: int, *, stalled: bool) -> str:
    """从终局状态推出 EPISODE_END 的 `reason`：成功 > 停摆 > 步数用尽 > 世界自己结束。

    `success`/`stalled` 都由调用方直接传值，不收 `obs` 进来拆字段——`stalled` 来自
    `state.stall_count >= STALL_LIMIT`，`success` 是 `judge` 的裁决
    （`EpisodeRunState.success`，跟观测本身脱钩），这个函数只吃裸值，不假装自己需要
    一份完整观测。
    """
    if success:
        return "success"
    if stalled:
        return "stalled"
    if step >= max_steps:
        return "max_steps_exceeded"
    return "world_ended"


def close_episode(state: EpisodeRunState, runtime: Runtime[HarnessDeps]) -> dict[str, Any]:
    """算结算、写 `EPISODE_END`。**只改 `outcome` 一处。**

    前置条件：`state.observation` 非空（本局至少有一帧）。
    后置条件：返回 `{"outcome": …}`；`outcome` 是子图的输出键，父侧 `reflect` 靠它拿
    本局结果（陈旧值不会报错，所以它必须由本格写出）。
    """
    deps = runtime.context
    obs = state.observation
    assert obs is not None, "close_episode before an observation exists"
    outcome = FromRunHarnessToEpisodeHarnessRunResp(
        episode_id=state.episode_id,
        success=state.success,
        steps=obs.step,
        reason=derive_episode_reason(
            state.success,
            obs.step,
            state.task.max_steps,
            stalled=state.stall_count >= STALL_LIMIT,
        ),
    )
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.EPISODE_END,
            step=outcome.steps,
            episode_id=state.episode_id,
            outcome_episode=outcome,
        )
    )
    return {"outcome": outcome}
