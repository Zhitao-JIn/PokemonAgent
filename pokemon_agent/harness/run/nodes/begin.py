"""`begin`：run 图的入口——初始目标表已由 `run_entry.new_run()` 装配进 state，这里只校验。

**不改任何一处 state**（返回空增量）：它是"进图的那一份 state 合不合法"的守门人。
校验放在图里而不是入口函数里，是因为它守的是**图的不变式**——目标表里至多一条
`RUNNING`，而这条不变式是 `dispatch`（盖 `RUNNING`）/ `review`（盖章改状态）两个节点
共同的前提；放节点里，`invoke` 一进图就炸，定位成本最低。

签名里的 `runtime` 本格用不到（入口不需要任何依赖），保留它是为了**全图统一签名**
`(state, runtime: Runtime[HarnessDeps]) -> dict`——这份形状本身就是节点的契约
（D5），而 `Runtime[...]` 的类型参数只能是 `HarnessDeps`（"context 只有一个类型"，
§5.3-④）。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness.domain import GoalStatus

from ...deps import HarnessDeps
from ..run_state import RunState


def begin(state: RunState, runtime: Runtime[HarnessDeps]) -> dict[str, Any]:
    """初始表已由 `run_entry.new_run()` 构造进 state——这里只做校验。**图的入口。**"""
    assert state.plan, "begin() got an empty goal table"
    running = [e for e in state.plan if e.status is GoalStatus.RUNNING]
    assert len(running) <= 1, "at most one RUNNING goal is allowed"
    return {}


__all__ = ["begin"]
