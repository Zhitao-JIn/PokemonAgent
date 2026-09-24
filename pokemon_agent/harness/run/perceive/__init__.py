"""`perceive` 格（run 层）：先吸收上一局的结算，再读规划与判定素材。

    absorb_episode → read_plan_context

与 episode（`absorb_task` → 取帧 → 检索）、task（取帧 → 写记忆 → 读记忆 → 动作空间）同构：
吸收上一圈的后果在 perceive，判定在 review_and_judge。顺序是契约——局索引按
`episode_outputs` 排执行序，得先把刚跑完那局收进去。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from ...compose import compose_units
from ..run_state import RunState
from ..runtime import RunRuntime
from .absorb_episode import absorb_episode
from .read_plan_context import read_plan_context

_UNITS = (absorb_episode, read_plan_context)


def perceive(state: RunState, runtime: Runtime[RunRuntime]) -> dict[str, Any]:
    """按序跑两个单元，返回全部增量的合并。"""
    # 步骤 1：吸收 → 读素材（顺序是契约）。
    return compose_units(state, runtime, _UNITS)


__all__ = ["perceive"]
