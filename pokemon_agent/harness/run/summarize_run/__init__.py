"""run 已判停后的蒸馏格：成功交正文，耗尽或无素材交空章。"""

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.errors import BudgetExhausted, MaxRetriesExceeded
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolSummarizeRunReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.memory import EpisodeMemory, RunMemory
from pokemon_agent.schemas.memory.datastore.task_memory import MemoryIndex

from ..run_state import RunState
from ..runtime import RunRuntime


def _chapter(state: RunState, reason: str) -> RunMemory:
    """用最终结算盖来源章；正文为空，原因保留在质量说明中。"""
    assert state.termination is not None
    return RunMemory(
        run_id=state.run_id,
        run_goal=state.run_goal.goal,
        episodes=len(state.episode_outputs),
        succeeded=sum(output.success for output in state.episode_outputs),
        acts_used=sum(output.acts_used for output in state.episode_outputs),
        termination=state.termination.value,
        reason=reason,
        summary="",
        quality_score=0.0,
        quality_rationale=reason,
        pointers=[output.episode_id for output in state.episode_outputs],
        index=MemoryIndex(),
    )


def _request(
    state: RunState,
    deps: RunRuntime,
    chapter: RunMemory,
    memories: list[EpisodeMemory],
) -> FromHarnessToBrainToolSummarizeRunReq:
    """来源章计数取最终结算；调用方保证终态与素材非空。"""
    assert state.termination is not None
    return FromHarnessToBrainToolSummarizeRunReq(
        run_id=state.run_id,
        run_goal=state.run_goal.goal,
        goals=state.goals,
        episode_memories=memories,
        termination=state.termination,
        judge_reason=state.judge_reason,
        episodes=chapter.episodes,
        succeeded=chapter.succeeded,
        acts_used=chapter.acts_used,
        max_episodes=deps.config.budget.max_episodes,
    )


def _record_exhaustion(
    deps: RunRuntime,
    meta: dict[str, object],
    exc: MaxRetriesExceeded | BudgetExhausted,
) -> None:
    """保留此前调用账，并为耗尽写一条错误账。"""
    if exc.calls:
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.SUMMARIZE_RUN_CALL, meta=meta, calls=list(exc.calls)
            )
        )
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.CALL_EXHAUSTED, meta=meta, link="summarize_run"
        )
    )


def summarize_run(state: RunState, runtime: Runtime[RunRuntime]) -> dict[str, Any]:
    """在 done 后执行；预算与重试耗尽均留账并降级，保证返回 run_memory。"""
    assert state.done and state.termination is not None, "run summary before termination"
    deps = runtime.context
    meta = {
        "source": "run.summarize_run",
        "episode_id": state.run_id,
        "task_id": state.run_id,
        "step": state.step + 1,
    }
    memories = [output.memory for output in state.episode_outputs if output.memory is not None]
    chapter = _chapter(state, "无可蒸素材")
    if not memories:
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.CALL_EXHAUSTED, meta=meta, link="summarize_run"
            )
        )
        return {"run_memory": chapter}
    req = _request(state, deps, chapter, memories)
    try:
        result = deps.run_summarizer.summarize_run(req)
    except (MaxRetriesExceeded, BudgetExhausted) as exc:
        _record_exhaustion(deps, meta, exc)
        return {"run_memory": _chapter(state, f"{type(exc).__name__}: {exc}")}
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.SUMMARIZE_RUN_CALL, meta=meta, calls=result.calls
        )
    )
    return {"run_memory": result.run_memory}
