"""`reflect`：看结算，决定"弹栈 / 重试 / 交人工"——run 图的重试闸口。

它只改 `outcomes`/`goals`/`attempts` 三处，**不做路由判断**：路由（失败且栈顶没弹
→ 直连 `dispatch` 重试）在 `run_graph.py` 的 `_should_retry`，因为"哪条边"属于
"图长什么样"。

`MAX_GOAL_RETRIES` 是"同一个目标自动重试几次"的实验旋钮，住顶层
`pokemon_agent/config.py`；它的唯一读者就是本节点。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.config import MAX_GOAL_RETRIES

from ...deps import HarnessDeps
from ..run_state import RunState


def goal_retries_exhausted(attempts_used: int) -> bool:
    """判断栈顶目标的重试预算是否耗尽。

    `attempts_used` 是 `dispatch` 已经把这个目标派发过的次数（这次失败也
    算一次派发，`reflect()` 调这个函数前已经 +1 过）；减 1 换算成"已经
    重试过几次"，达到或超过 `MAX_GOAL_RETRIES` 就是预算耗尽——`reflect()`
    据此决定强制弹栈还是直连重试。
    """
    retries_used = attempts_used - 1
    return retries_used >= MAX_GOAL_RETRIES


def reflect(state: RunState, runtime: Runtime[HarnessDeps]) -> dict[str, Any]:
    """看结算：**成功才弹栈**；失败按重试预算分流（路由见 `run_graph._should_retry`）。

    预算内失败 → 栈顶保留（goals/attempts 原样），直连 dispatch 重试；
    预算耗尽（已派发 `1 + MAX_GOAL_RETRIES` 次）→ 强制弹出、放弃该目标，
    交人工 review 处置。无论哪种，结算都累积进 `outcomes`。

    `runtime` 本格用不到（弹栈/重试纯看 state）——留着是为全图统一签名，理由见
    `begin.py` 的文件文档。
    """
    assert state.outcome is not None, "reflect() without a fresh outcome"
    assert len(state.attempts) == len(state.goals), "attempts must parallel goals"
    outcomes = state.outcomes + [state.outcome]

    if state.outcome.success:
        return {
            "outcomes": outcomes,
            "goals": state.goals[:-1],
            "attempts": state.attempts[:-1],
        }

    if goal_retries_exhausted(state.attempts[-1]):
        return {
            "outcomes": outcomes,
            "goals": state.goals[:-1],
            "attempts": state.attempts[:-1],
        }
    return {"outcomes": outcomes}


__all__ = ["goal_retries_exhausted", "reflect"]
