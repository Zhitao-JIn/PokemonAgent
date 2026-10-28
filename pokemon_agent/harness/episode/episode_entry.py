"""episode 图的**图外侧门**：`begin_episode`（装配初值）/ `run_episode`（进图取结算）/ `close`。

与 `task_entry` / `run_entry` 同形：run 的 `act` 只调 `run_episode`。入口只写开局账、装初值，
**不接异常**——整局异常由接住它的 run 层 `act` 记 `episode_error`（谁接住谁记账）；
**不向世界取帧**——每层只有 perceive 格取帧（episode 用完整档，task 用 RAM 档）。
**冻结的 task 表在这里装成初始状态**：`loop.freeze_episode_plan` 打开时用
`EpisodeInput.tasks`（样本给的）按表序装表并给出 `execution_order`；开关关着时
`tasks` 被忽略，任务表仍由 `plan_episode` 问 decomposer 拆。
世界起点（`game.reset`）不在这里：每 run 一次，在 `run_entry.new_run`。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph.state import CompiledStateGraph

from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind
from pokemon_agent.schemas.harness.domain import EpisodeInput, EpisodeOutput, TaskEntry

from .episode_runtime import EpisodeRuntime
from .episode_state import EpisodeContext, EpisodeRunState


def exc_snapshot(exc: Exception) -> str:
    """异常的字符串快照（`episode_error` 的 `error` 字段只吃文本）。"""
    return f"{type(exc).__name__}: {exc}"


def begin_episode(deps: EpisodeRuntime, episode_input: EpisodeInput) -> EpisodeRunState:
    """开一局：写 EPISODE_START，返回初始状态。**不取帧**——取帧只在图内 perceive。

    前置条件：`loop.freeze_episode_plan` 打开时 `episode_input.tasks` 非空——空表是样本
    数据错误，不静默退回自由规划（D6）；表里 `task_id` 在本局内唯一。
    后置条件：开关打开时 `state.tasks` 按样本表序装好（全 `PENDING`、`round=1`），
    `state.execution_order` 同序给出；开关关着时两者都为空（`tasks` 被忽略，自由规划自己拆）。
    """
    episode_id = episode_input.episode_id

    # 步骤 1：开局账。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.EPISODE_START,
            meta={
                "source": "episode_entry.begin_episode",
                "episode_id": episode_id,
                "task_id": "",
                "step": 0,
            },
            task=episode_input.goal,
        )
    )

    # 步骤 2：冻结的 task 表（开关关着就是空表）。
    tasks = _frozen_tasks(deps, episode_input)

    # 步骤 3：组装初始状态（不取帧：第一帧由图内 perceive 的 sense 取）。
    state = EpisodeRunState(
        run_id=episode_input.run_id,
        run_goal=episode_input.run_goal,
        episode_id=episode_id,
        goal=episode_input.goal,
        ep_ctx=EpisodeContext(),
        actions_budget=episode_input.actions_budget,
        remaining_s=episode_input.remaining_s,
        tasks=tasks,
        execution_order=[entry.entry_id for entry in tasks],
    )
    return state


def _frozen_tasks(deps: EpisodeRuntime, episode_input: EpisodeInput) -> list[TaskEntry]:
    """把样本给的 task 表装成初始 `TaskEntry`；开关关着返回空表（`tasks` 一律忽略）。"""
    if not deps.config.loop.freeze_episode_plan:
        return []
    assert episode_input.tasks, "freeze_episode_plan needs a non-empty task table"
    entries = [TaskEntry(entry_id=task.task_id, task=task, round=1) for task in episode_input.tasks]
    ids = [entry.entry_id for entry in entries]
    assert len(set(ids)) == len(ids), "frozen task ids must be unique within an episode"
    return entries


def run_episode(
    deps: EpisodeRuntime, graph: CompiledStateGraph, *, episode_input: EpisodeInput
) -> EpisodeOutput:
    """跑完一局：装配 → 进图 → 取结算。异常原样上抛（run 层 `act` 接住并记 `episode_error`）。"""
    assert episode_input.goal.max_steps > 0, "episode max_steps (task count) must be > 0"
    state = begin_episode(deps, episode_input)
    final = graph.invoke(
        state, {"recursion_limit": deps.config.loop.episode_recursion_limit}, context=deps
    )
    return close(final, episode_input, hard_limit=deps.config.budget.episode_max_tasks)


def close(final: dict[str, Any], episode_input: EpisodeInput, *, hard_limit: int) -> EpisodeOutput:
    """取出 `close_episode` 写好的结算，并断言 task 数没有越过预算。"""
    state = EpisodeRunState.model_validate(final)
    assert state.output is not None, "episode graph ended without close_episode"
    assert state.output.tasks_used <= hard_limit, (
        f"episode ran {state.output.tasks_used} tasks > configured_limit={hard_limit}"
    )
    return state.output


__all__ = ["begin_episode", "close", "exc_snapshot", "run_episode"]
