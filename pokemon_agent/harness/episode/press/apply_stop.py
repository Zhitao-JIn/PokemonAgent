"""`apply_stop`：按 `stop` 的作废范围截队；**只在真的丢了键时**留一条 `ACTION_TRUNCATED`。

改 `pending_presses` 一处；写一条账（可选的）——"截断了没有、丢了哪些键"是执行层处置
自己的动作，与"这一键看到了什么"（上一格 `perceive_after_action` 的 `AFTER_ACTION`）
是两笔账：后者链内每键一条，前者**只在真丢键时**一条。

**为什么"截断"要单独成账、而且是条件账**：`stop` 有三种（`blocked`/`warp`/
`episode_over`），但**中止不等于截断**——`up×1 -> down×2` 里第一下撞墙时本段剩余为零，
一个键都不用丢，链照常往下走。把 `stop` 挂在恒有值的字段上，读的人得自己判断"这条 stop
有没有兑现成动作"，"这一局被截断了几次"也只能靠重算。于是 `stop` 只进
`ACTION_TRUNCATED`（处置账），`AFTER_ACTION`（观察账）不带它——"看到什么"与"据此处置了
什么"分开（见 `docs/spec/harness/PLAN_graph_readability.md` §3.7.2/§3.7.3）。

**`stop` 为什么挂在这里、不挂 `ACT`**：`ACT` 写在按键那一刻，那时世界还没动，结果根本
不存在（`PLAN_action_step_granularity.md` §5 的 v4 修订）。

**执行层不悄悄改写大脑交出来的链**：截断这件事由 `ACTION_TRUNCATED` 留痕（`stop` 另经
`StepMemory` 传给大脑），大脑下一步读得到，自己就能推出"在第 3 键撞墙了"。

**帧不归这一格**：帧由 `perceive_after_action` 挂在自己的 `AFTER_ACTION` 上，这一格只
处置队列。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.brain import ActionSegment
from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind
from pokemon_agent.schemas.memory import StopReason

from ...deps import HarnessDeps
from ..episode_state import EpisodeRunState


def apply_stop(state: EpisodeRunState, runtime: Runtime[HarnessDeps]) -> dict[str, Any]:
    """按作废范围截断队列，必要时写一条 `ACTION_TRUNCATED`。**只改 `pending_presses` 一处。**

    作废范围（唯一判据见 `PLAN_action_step_granularity.md` §5，只扩到"再做下去会产生它
    没打算要的动作"为止）：

    - `blocked`：丢掉从队首起的**整段同名键**（`up×4 -> down×2` 里第 2 个 up 撞墙 →
      丢掉后面两个 up，`down` 照按）；
    - `warp`/`episode_over`：整条链作废。

    前置条件：`observation`/`action`/`pending_observation` 非空（前两格已跑过）。
    后置条件：返回 `{"pending_presses": 截断后的队列}`。
    """
    deps = runtime.context
    assert state.observation is not None, "apply_stop before act"
    assert state.action is not None, "apply_stop without an action"
    assert state.pending_observation is not None, "apply_stop before perceive"
    action = state.action
    stop = state.pending_stop

    # 步骤 1：按作废范围截断队列。（`act` 已经弹掉队首，所以"队列空"就是
    # "刚按的这一个是链尾"。）
    presses = list(state.pending_presses)
    dropped: list[ActionSegment] = []
    if stop is StopReason.BLOCKED:
        # 本段剩余次数。展开之后同一段的键在队列里是连续的，而"这一下撞墙"意味着
        # 后面同方向的每一下撞的都是同一面墙（朝向已经就是那个方向，再按也不会动）——
        # 所以丢掉从队首起的整段同名键。丢得刚好够。
        name = action.sequence[0].name
        while presses and presses[0].name == name:
            dropped.append(presses.pop(0))
    elif stop is not None:
        # `warp`（新地图上没规划过）与 `episode_over`（本局到点了）：整条链作废。
        dropped, presses = presses, []

    # 步骤 2：**只有真的丢了键才写这条处置账**——一个键都没丢时不写，"被截断了几次"
    # 于是可以直接数事件条数（数 `ACTION_TRUNCATED` 的条数）。
    if dropped:
        assert stop is not None, "dropped keys imply a stop reason"
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.ACTION_TRUNCATED,
                episode_id=state.episode_id,
                step=state.observation.step,
                stop=stop.value,
                dropped=dropped,
            )
        )
    return {"pending_presses": presses}
