"""`perceive` 格（run 层）：先吸收上一局的结算，再取一帧、读规划与判定素材。

    absorb_episode → sense → read_plan_context → retrieve_run_knowledge

与 episode（`absorb_task` → 取帧 → 检索）、task（取帧 → 写记忆 → 读记忆 → 动作空间）同构：
吸收上一圈的后果在 perceive，判定在 review_and_judge。顺序是契约——全部局详情按
`episode_outputs` 排执行序、`total_acts` 的跨局累加也在吸收里（sense 盖章要用），
得先把刚跑完那局收进去。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from ...compose import compose_units
from ..run_state import RunState
from ..runtime import RunRuntime
from .absorb_episode import absorb_episode
from .read_plan_context import read_plan_context
from .retrieve_run_knowledge import retrieve_run_knowledge
from .sense import sense

_UNITS = (absorb_episode, sense, read_plan_context, retrieve_run_knowledge)


def perceive(state: RunState, runtime: Runtime[RunRuntime]) -> dict[str, Any]:
    """按序跑四个单元，返回全部增量的合并。"""
    # 步骤 1：吸收 → 取帧 → 读素材 → 检索知识（顺序是契约）。
    return compose_units(state, runtime, _UNITS)


__all__ = ["perceive"]
