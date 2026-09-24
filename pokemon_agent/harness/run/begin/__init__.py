"""`begin`：run 图的入口——初始目标表已由 `run_entry.new_run()` 装配进 state，这里校验并记开局账。

**不改任何一处 state**（返回空增量）。校验放在图里，是因为它守的是**图的不变式**——
目标表里至多一条 `RUNNING`，这是 `act`（盖 `RUNNING`）/ `review_and_judge`（盖章）共同的前提。

开局账 `run_start` 记在这里（与 `run_end` 记在 `run_done` 对称）：一个 run 的起止都在图内的
首尾两格；图外 `run_entry.new_run` 只记它亲手接住的 `run_error`。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind
from pokemon_agent.schemas.harness.domain import EntryStatus

from ..run_state import RunState
from ..runtime import RunRuntime


def begin(state: RunState, runtime: Runtime[RunRuntime]) -> dict[str, Any]:
    """校验初始目标表，记 `run_start`。**图的入口。**"""
    # 步骤 1：校验。
    assert state.goals, "begin() got an empty goal table"
    running = [e for e in state.goals if e.status is EntryStatus.RUNNING]
    assert len(running) <= 1, "at most one RUNNING goal is allowed"

    # 步骤 2：开局账（run 级账：meta 的 episode_id / task_id 位放 run_id）。
    runtime.context.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.RUN_START,
            meta={
                "source": "run.begin",
                "episode_id": state.run_id,
                "task_id": state.run_id,
                "step": state.step,
            },
            run_goals=[entry.task for entry in state.goals],
            run_goal=state.run_goal,
        )
    )
    return {}


__all__ = ["begin"]
