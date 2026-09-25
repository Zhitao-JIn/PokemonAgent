"""`settle_episode_error`：整局抛错时的收场——补空章、记 `episode_error`、兜成 `ERROR` 结算。"""

from __future__ import annotations

from pokemon_agent.errors import AgentError
from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind
from pokemon_agent.schemas.harness.domain import EpisodeInput, EpisodeOutput, Termination

from ...episode import episode_entry
from ...episode.episode_done.leave_chapter import store_empty_chapter
from ...episode.episode_runtime import EpisodeRuntime


def settle_episode_error(
    deps: EpisodeRuntime, run_id: str, episode_input: EpisodeInput, exc: Exception, *, source: str
) -> EpisodeOutput:
    """补空章 → 记 `episode_error`；`AgentError` 兜成 `ERROR` 结算，别的原样上抛。

    补空章保证"一局恰好一条 EpisodeMemory"：episode 图已经死了，只能由接住它的人代写。
    source：接住异常的位置（`"run.act"` / `"checkpoint.restore"`），
        记进空章与 `episode_error` 的 `source`。
    """
    episode_id = episode_input.episode_id
    reason = f"error: {type(exc).__name__}"
    store_empty_chapter(
        deps,
        run_id=run_id,
        episode_id=episode_id,
        goal=episode_input.goal.goal,
        tasks_used=0,
        acts_used=0,
        termination=Termination.ERROR,
        reason=reason,
        source=source,
        step=0,
    )
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.EPISODE_ERROR,
            meta={"source": source, "episode_id": episode_id, "task_id": episode_id, "step": 0},
            error=episode_entry.exc_snapshot(exc),
        )
    )
    if not isinstance(exc, AgentError):
        raise exc
    return EpisodeOutput(
        episode_id=episode_id,
        goal_id=episode_input.goal.task_id,
        termination=Termination.ERROR,
        judge_reason="这一局抛错，未经判定",
        reason=reason,
        tasks_used=0,
        acts_used=0,
    )


__all__ = ["settle_episode_error"]
