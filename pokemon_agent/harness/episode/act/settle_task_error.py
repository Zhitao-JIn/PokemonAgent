"""`settle_task_error`：task 抛错时的收场——记 `task_error`，`AgentError` 兜成 `ERROR` 结算。"""

from __future__ import annotations

from pokemon_agent.errors import AgentError
from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind
from pokemon_agent.schemas.harness.domain import TaskInput, TaskOutput, Termination

from ...task.task_entry import exc_snapshot
from ..episode_runtime import EpisodeRuntime


def settle_task_error(
    deps: EpisodeRuntime, task_input: TaskInput, exc: Exception, *, source: str
) -> TaskOutput:
    """记 `task_error`；`AgentError` 兜成 `ERROR` 结算，别的原样上抛。

    `steps_used` 从账上数（这个 task 已落的 `press_key` 条数）：键已经按出去了，
    下一个 task 的键号基数得跟着往后挪，否则帧号会重。
    source：接住异常的位置（`"episode.act"` / `"checkpoint.restore"`），
        记进 `task_error` 的 `meta.source`。
    """
    task_id = task_input.task.task_id
    presses = sum(
        1
        for ev in deps.trace.read_events(
            {"run_id": task_input.run_id, "episode_id": task_input.episode_id, "task_id": task_id}
        )
        if ev.kind == TraceKind.PRESS_KEY
    )
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.TASK_ERROR,
            meta={
                "source": source,
                "episode_id": task_input.episode_id,
                "task_id": task_id,
                "step": task_input.start_step + presses,
            },
            error=exc_snapshot(exc),
        )
    )
    if not isinstance(exc, AgentError):
        raise exc
    return TaskOutput(
        task_id=task_id,
        termination=Termination.ERROR,
        judge_reason="这个 task 抛错，未经判定",
        reason=f"error: {type(exc).__name__}",
        steps_used=presses,
    )


__all__ = ["settle_task_error"]
