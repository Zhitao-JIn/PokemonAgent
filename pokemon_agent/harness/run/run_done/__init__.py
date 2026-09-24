"""`run_done` 格（run 层）：**终止唯一出口**——组装 `RunResp`、记 `run_end`。

`termination` / `judge_reason` 已由 `review_and_judge` 写好；run 层暂无 LLM 结论调用，
本格只结算、记账，不改状态。图外 `run_entry.close` 用同一个
`settle_run` 拆出返回值。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, RunResp, TraceKind

from ..run_state import RunState
from ..runtime import RunRuntime


def settle_run(state: RunState) -> RunResp:
    """从终态组装 run 级结算。前置条件：`termination` 非空。"""
    outcomes = state.episode_outputs
    succeeded = sum(1 for o in outcomes if o.success)
    return RunResp(
        run_id=state.run_id,
        outcomes=outcomes,
        total=len(outcomes),
        succeeded=succeeded,
        success_rate=(succeeded / len(outcomes)) if outcomes else 0.0,
        termination=state.termination,
        judge_reason=state.judge_reason,
    )


def run_done(state: RunState, runtime: Runtime[RunRuntime]) -> dict[str, Any]:
    """记 `run_end`，不改状态。"""
    assert state.done and state.termination is not None, "run_done before the run finished"
    runtime.context.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.RUN_END,
            meta={
                "source": "run_done",
                "episode_id": state.run_id,
                "task_id": state.run_id,
                "step": state.step,
            },
            outcome_run=settle_run(state),
        )
    )
    return {}


__all__ = ["run_done", "settle_run"]
