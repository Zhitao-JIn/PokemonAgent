"""`act` 格（episode 层）：**派一个 task**——任务表里第一条 PENDING 标 RUNNING、拼 `TaskInput`、
经 `task_entry.run_task` 跑完 task 子图，把 `TaskOutput` 写进 `pending_task`。

吸收结算（键数、失败连击）在下一圈的 `perceive`，盖章在下一圈的 `review_and_judge`；
本格出口无条件回 `perceive`。

**task 抛错由本格接住**（谁接住谁记账）：记 `task_error`；`AgentError`（预期内的单个 task
失败）兜成一份 `ERROR` 的 `TaskOutput`——这一局照常往下走，review 把它盖成 FAILED；
别的异常是 bug，记完原样上抛。
task 子图编译一次、缓存（import 期不建图、调用期不重建）。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from pokemon_agent.errors import AgentError
from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind
from pokemon_agent.schemas.harness.domain import EntryStatus, TaskInput, TaskOutput, Termination

from ...task import compile_task_graph
from ...task.task_entry import exc_snapshot, run_task
from ..episode_runtime import EpisodeRuntime
from ..episode_state import EpisodeRunState

_task_graph: CompiledStateGraph | None = None


def task_graph() -> CompiledStateGraph:
    """task 子图：编译一次、缓存。"""
    global _task_graph
    if _task_graph is None:
        _task_graph = compile_task_graph()
    return _task_graph


def act(state: EpisodeRunState, runtime: Runtime[EpisodeRuntime]) -> dict[str, Any]:
    """派第一条 PENDING，返回 `{"pending_task", "tasks", "step"}`。

    前置条件：任务表里有 PENDING（`plan_episode` 保证）。
    """
    index = next(
        (i for i, entry in enumerate(state.tasks) if entry.status is EntryStatus.PENDING), None
    )
    assert index is not None, "act without a PENDING task (plan_episode should prevent this)"
    entry = state.tasks[index]

    # 步骤 1：标 RUNNING，装配 TaskInput（键号基数 = 本局累计键数）。
    running = entry.model_copy(update={"status": EntryStatus.RUNNING})
    task_input = TaskInput(
        run_id=state.run_id,
        episode_id=state.episode_id,
        task=entry.task,
        start_step=state.total_acts,
    )

    # 步骤 2：跑 task 子图，结算交给下一圈 perceive 吸收、review 盖章；抛错由本格接住。
    try:
        output = run_task(runtime.context.task, task_graph(), task_input=task_input)
    except Exception as exc:
        output = _task_error(runtime.context, task_input, exc)
    tasks = [*state.tasks[:index], running, *state.tasks[index + 1 :]]
    return {"pending_task": output, "tasks": tasks, "step": state.step + 1}


def _task_error(deps: EpisodeRuntime, task_input: TaskInput, exc: Exception) -> TaskOutput:
    """记 `task_error`；`AgentError` 兜成 `ERROR` 结算，别的原样上抛。

    `steps_used` 从账上数（这个 task 已落的 `press_key` 条数）：键已经按出去了，
    下一个 task 的键号基数得跟着往后挪，否则帧号会重。
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
                "source": "episode.act",
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


__all__ = ["act", "task_graph"]
