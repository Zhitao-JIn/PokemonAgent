"""`act`：弹出队首那**一个键**，推进世界。**只有它推进世界。**

只管执行和账，不写记忆、不感知——改 `action`/`pending_presses` 两处（"弹队首"这一个
动作的两面）。当前帧不由这一格扶正（那是 `close_step` 的活）：`observation` 在本圈里的
语义是"这次按键**之前**的那一帧"，`perceive_after_action` 拿它当 `before` 判中止，
两个 store 拿它跟 `pending_observation` 凑成 `before`/`after` 反思记忆。

**派生而不是新建类型**：`reflect`/trace/停摆检测/记忆全都只认 `Action`，
派生出来的那个照样是"这一步要做的动作"（单段、`times=1`），所以它们一个都不用知道
"链"这个概念存在。`thought` 沿用 `plan` 的（链级的，只进 trace），`rationale` 取自
队首所在的那一段。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.brain import Action
from pokemon_agent.schemas.harness import (
    FromHarnessToGameToolExecuteReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)

from ...deps import HarnessDeps
from ..episode_state import EpisodeRunState


def act(state: EpisodeRunState, runtime: Runtime[HarnessDeps]) -> dict[str, Any]:
    """弹队首一键，执行，写 `ACT`。**只改 `action`/`pending_presses` 两处。**

    **`settle` 由"这是不是队列里的最后一个键"决定**：链中间的键后面还有键要按，等世界
    把 10 秒过场走完不但慢，而且那几帧对它没用（它只读内存判位移、换图）；链尾那一帧要
    交给 `judge` 看，必须等。

    `step` 不在这里加（在 `close_step` 里加，`ACT` 与 `MEMORY_WRITE` 落在同一步上）。
    感知在下一格 `perceive_after_action`——一帧只在产出处感知一次，这里不盖。

    前置条件：`state.observation`/`state.plan` 非空、`pending_presses` 非空。
    后置条件：返回 `{"action": 单键动作, "pending_presses": 剩余队列}`。
    """
    deps = runtime.context
    assert state.observation is not None, "act before close_step"
    assert state.plan is not None, "act without a plan"
    assert state.pending_presses, "act with an empty pending queue"
    # 一切"按键之前"的判断都照着当前帧——它已由上一步的终点扶正好。
    ep, before = state.episode_id, state.observation

    # 步骤 1：派生这一圈的单键动作。
    head = state.pending_presses[0]
    is_decision_tail = len(state.pending_presses) == 1
    action = Action(thought=state.plan.thought, sequence=[head])

    # 步骤 2：按 `before` 这份观测执行（工具层照它验掩码），只推进世界，不感知。
    deps.game.execute(
        FromHarnessToGameToolExecuteReq(action=action, observation=before, settle=is_decision_tail)
    )

    # 步骤 3：写 ACT，交给下一格 perceive_after_action 去感知。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.ACT,
            episode_id=ep,
            step=before.step,
            action=action,
        )
    )
    # 两处一起交：派生的单键动作、剩下的队列（当前帧的扶正在 `close_step`）。
    return {
        "action": action,
        "pending_presses": state.pending_presses[1:],
    }
