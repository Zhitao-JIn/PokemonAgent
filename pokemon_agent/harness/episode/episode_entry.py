"""episode 图的**图外侧门**：`begin_episode`（装配初值）/ `run_episode`（进图取结算）/ `close`。

与 `task_entry` / `run_entry` 同形：run 的 `act` 只调 `run_episode`。入口只写开局账、装初值，
**不接异常**——整局异常由接住它的 run 层 `act` 记 `episode_error`（谁接住谁记账）；
**不向世界取帧**——每层只有 perceive 格取帧（episode 用完整档，task 用 RAM 档）。
世界起点（`game.reset`）不在这里：每 run 一次，在 `run_entry.new_run`。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph.state import CompiledStateGraph

from pokemon_agent.config import EPISODE_RECURSION_LIMIT
from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind
from pokemon_agent.schemas.harness.domain import EpisodeInput, EpisodeOutput

from .episode_runtime import EpisodeRuntime
from .episode_state import EpisodeContext, EpisodeRunState


def exc_snapshot(exc: Exception) -> str:
    """异常的字符串快照（`episode_error` 的 `error` 字段只吃文本）。"""
    return f"{type(exc).__name__}: {exc}"


def begin_episode(deps: EpisodeRuntime, episode_input: EpisodeInput) -> EpisodeRunState:
    """开一局：写 EPISODE_START，返回初始状态。**不取帧**——取帧只在图内 perceive。"""
    episode_id = episode_input.episode_id

    # 步骤 1：开局账。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.EPISODE_START,
            meta={
                "source": "episode_entry.begin_episode",
                "episode_id": episode_id,
                "task_id": episode_id,
                "step": 0,
            },
            task=episode_input.goal,
        )
    )

    # 步骤 2：组装初始状态（不取帧：第一帧由图内 perceive 的 sense 取）。
    return EpisodeRunState(
        run_id=episode_input.run_id,
        episode_id=episode_id,
        goal=episode_input.goal,
        ep_ctx=EpisodeContext(),
    )


def run_episode(
    deps: EpisodeRuntime, graph: CompiledStateGraph, *, episode_input: EpisodeInput
) -> EpisodeOutput:
    """跑完一局：装配 → 进图 → 取结算。异常原样上抛（run 层 `act` 接住并记 `episode_error`）。"""
    assert episode_input.goal.max_steps > 0, "episode max_steps (task count) must be > 0"
    state = begin_episode(deps, episode_input)
    final = graph.invoke(state, {"recursion_limit": EPISODE_RECURSION_LIMIT}, context=deps)
    return close(final, episode_input)


def close(final: dict[str, Any], episode_input: EpisodeInput) -> EpisodeOutput:
    """取出 `close_episode` 写好的结算，并断言 task 数没有越过预算。"""
    state = EpisodeRunState.model_validate(final)
    assert state.output is not None, "episode graph ended without close_episode"
    assert state.output.tasks_used <= episode_input.goal.max_steps, (
        f"episode ran {state.output.tasks_used} tasks > max_steps={episode_input.goal.max_steps}"
    )
    return state.output


__all__ = ["begin_episode", "close", "exc_snapshot", "run_episode"]
