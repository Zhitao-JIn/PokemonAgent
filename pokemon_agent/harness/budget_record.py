"""预算收紧、跳过与机械盖章的记账；不调用模型或人审。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pokemon_agent.direct.interface import TraceToolPort
from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind
from pokemon_agent.schemas.harness.domain import EntryStatus, Termination

if TYPE_CHECKING:
    from .episode.episode_runtime import EpisodeRuntime
    from .episode.episode_state import EpisodeRunState
    from .run.run_state import RunState
    from .run.runtime import RunRuntime
    from .task.task_runtime import TaskRuntime
    from .task.task_state import TaskState


def budget_meta(state: Any, layer: str, source: str) -> dict[str, object]:  # noqa: ANN401
    """按三层账面位置返回四个调用方标签。"""
    return {
        "source": f"{layer}.{source}",
        "episode_id": state.run_id if layer == "run" else state.episode_id,
        "task_id": state.run_id
        if layer == "run"
        else state.task.task_id
        if layer == "task"
        else "",
        "step": state.step + 1,
    }


def record_budget(
    trace: TraceToolPort,
    meta: dict[str, object],
    kind: TraceKind,
    **content: object,  # noqa: ANN401
) -> None:
    """预算策略变化显式记账；使用既有 text 信封字段。"""
    trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=kind,
            meta=meta,
            text=json.dumps(content, ensure_ascii=False),
        )
    )


def settle_running(
    state: RunState | EpisodeRunState | TaskState,
    deps: RunRuntime | EpisodeRuntime | TaskRuntime,
    layer: str,
    reason: Termination,  # noqa: ANN401
) -> dict[str, object]:
    """已有子图结算按机器判定盖章；不再请模型或人审覆盖预算停止。"""
    if layer == "task":
        return {}
    name = "goals" if layer == "run" else "tasks"
    outputs = state.episode_outputs if layer == "run" else state.task_outputs
    entries = list(getattr(state, name))
    for index, entry in enumerate(entries):
        if entry.status is not EntryStatus.RUNNING:
            continue
        outcome = outputs[-1] if outputs else None
        fields: dict[str, object] = {
            "status": EntryStatus.COMPLETED
            if outcome and outcome.success
            else EntryStatus.BLOCKED
            if outcome and outcome.termination is Termination.BLOCKED
            else EntryStatus.FAILED,
            "note": reason.value,
        }
        if layer == "run" and outcome is not None:
            fields["last_episode_id"] = outcome.episode_id
        if layer == "episode" and outcome is not None:
            assert outcome.entry_id == entry.entry_id and outcome.task_id == entry.last_task_id
        entries[index] = entry.model_copy(update=fields)
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.SETTLE_GOAL if layer == "run" else TraceKind.SETTLE_TASK,
                meta=budget_meta(state, layer, "budget_stop"),
                audit="skipped",
                fail_streak=state.fail_streak,
                **({"goal": entries[index]} if layer == "run" else {"task_entry": entries[index]}),
            )
        )
    return {name: entries}
