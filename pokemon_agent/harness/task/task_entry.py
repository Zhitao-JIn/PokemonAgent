"""task 图的**图外侧门**：`begin_task`（装配初值）/ `run_task`（进图取结算）/ `close`。

与 `episode_entry` / `run_entry` 同形：父层的 `act` 只调 `run_task`，
不直接 `invoke` 子图——初值装配与结算取出各只有这一处实现。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph.state import CompiledStateGraph

from pokemon_agent.config import NODES_PER_DECISION, NODES_PER_PRESS, RECURSION_MARGIN
from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind
from pokemon_agent.schemas.harness.domain import TaskInput, TaskOutput

from ..budget_record import budget_meta, record_budget
from .task_runtime import TaskRuntime
from .task_state import TaskState


def begin_task(deps: TaskRuntime, task_input: TaskInput) -> TaskState:
    """存一份 task 级存档（有存档器时），写 `task_start`，把 `TaskInput` 装成进图初值。

    存档先于开局账：存档账是从它恢复出的新线的分叉点，开局账要落在分叉点之后
    （否则新线的可见历史里会有父线的这条开局账，外加它自己重写的一条）。
    不取帧：开局帧由图内 perceive 取。
    """
    assert task_input.task.max_steps > 0, "task max_steps must be > 0"

    # 步骤 1：task 级存档（世界 + 记忆 + run / episode 两张图的定位）。
    if deps.checkpointer is not None:
        deps.checkpointer.save(
            "task",
            run_id=task_input.run_id,
            step=task_input.total_acts,
            episode_id=task_input.episode_id,
            task_id=task_input.task.task_id,
        )

    # 步骤 2：开局账。账面步号 dispatch 落 0（0928 定稿：圈号语义，每圈取帧 +1）；
    # content.total_acts 保留局内累计键数快照（记忆 / 帧槽键控用，与账面步号解耦）。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.TASK_START,
            meta={
                "source": "task_entry.begin_task",
                "episode_id": task_input.episode_id,
                "task_id": task_input.task.task_id,
                "step": 0,
            },
            task=task_input.task,
            entry_id=task_input.entry_id,
            total_acts=task_input.total_acts,
        )
    )

    # 步骤 3：组装初始状态。
    state = TaskState(
        run_id=task_input.run_id,
        episode_id=task_input.episode_id,
        entry_id=task_input.entry_id,
        task=task_input.task.model_copy(
            update={
                "max_steps": min(task_input.task.max_steps, deps.budget.task_max_steps),
            }
        ),
        total_acts=task_input.total_acts,
        knowledge=task_input.knowledge,
        task_index=task_input.task_index,
        actions_budget=task_input.actions_budget,
        remaining_s=task_input.remaining_s,
    )
    if state.task.max_steps != task_input.task.max_steps:
        record_budget(
            deps.trace,
            budget_meta(state, "task", "begin_task"),
            TraceKind.BUDGET_CLAMPED,
            original=task_input.task.max_steps,
            clamped=state.task.max_steps,
        )
    return state


def task_budget(task_input: TaskInput) -> int:
    """task 图的 `recursion_limit`：键预算 × 每键节点数 + 余量（贴身闸）。"""
    return task_input.task.max_steps * (NODES_PER_DECISION + NODES_PER_PRESS) + RECURSION_MARGIN


def exc_snapshot(exc: Exception) -> str:
    """异常的字符串快照（`task_error` 的 `error` 字段只吃文本；episode 层 `act` 用）。"""
    return f"{type(exc).__name__}: {exc}"


def run_task(deps: TaskRuntime, graph: CompiledStateGraph, *, task_input: TaskInput) -> TaskOutput:
    """跑完一个 task：装配 → 进图 → 取结算。

    异常原样上抛（episode 层 `act` 接住并记 `task_error`）。
    """
    state = begin_task(deps, task_input)
    final = graph.invoke(state, {"recursion_limit": task_budget(task_input)}, context=deps)
    return close(final, task_input)


def close(final: dict[str, Any], task_input: TaskInput) -> TaskOutput:
    """取出 `close_task` 写好的结算，并断言键数没有越过预算。"""
    state = TaskState.model_validate(final)
    assert state.output is not None, "task graph ended without close_task"
    assert state.output.steps_used <= task_input.task.max_steps, (
        f"task ran {state.output.steps_used} keys > max_steps={task_input.task.max_steps}"
    )
    return state.output


__all__ = ["begin_task", "close", "exc_snapshot", "run_task", "task_budget"]
