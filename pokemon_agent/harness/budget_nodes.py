"""三层节点的预算闸门：先吸收结算，持久化余额，再选择普通节点或机械收尾。"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from langgraph.runtime import Runtime

from pokemon_agent.errors import BudgetExhausted
from pokemon_agent.schemas.harness import FromHarnessToTraceToolAppendReq, TraceKind
from pokemon_agent.schemas.harness.domain import Termination

from .budget_record import budget_meta, record_budget, settle_running
from .judging import record_verdict

if TYPE_CHECKING:
    from .episode.episode_runtime import EpisodeRuntime
    from .episode.episode_state import EpisodeRunState
    from .run.run_state import RunState
    from .run.runtime import RunRuntime
    from .task.task_runtime import TaskRuntime
    from .task.task_state import TaskState

BUDGET_TERMINATIONS = frozenset(
    (
        Termination.TIME_EXHAUSTED,
        Termination.ACTIONS_EXHAUSTED,
        Termination.TASKS_EXHAUSTED,
        Termination.DECOMPOSITIONS_EXHAUSTED,
        Termination.PLANNING_EXHAUSTED,
    )
)
_CALL_KINDS = {
    "choose": TraceKind.CHOOSE_CALL,
    "plan": TraceKind.PLAN_CALL,
    "decompose": TraceKind.DECOMPOSE_CALL,
    "judge": TraceKind.JUDGE_CALL,
    "verify": TraceKind.VERIFY_CALL,
    "summarize_episode": TraceKind.SUMMARIZE_EPISODE_CALL,
    "summarize_task": TraceKind.SUMMARIZE_TASK_CALL,
}


def budget_reason(
    state: RunState | EpisodeRunState | TaskState,
    deps: RunRuntime | EpisodeRuntime | TaskRuntime,
    layer: str,
    source: str,
) -> Termination | None:
    """总量停止优先于继续请求；本局任务数和拆解次数只限制本局。"""
    if source == "begin":
        return None
    deadline = deps.deadline
    if deadline is not None and deadline.remaining() <= deps.config.budget.reserve_s:
        return Termination.TIME_EXHAUSTED
    outputs = (
        state.episode_outputs
        if layer == "run"
        else state.task_outputs
        if layer == "episode"
        else []
    )
    if outputs and outputs[-1].termination in (
        Termination.TIME_EXHAUSTED,
        Termination.ACTIONS_EXHAUSTED,
    ):
        return outputs[-1].termination
    used = (
        state.actions_used
        if layer == "run"
        else state.total_acts
        if layer == "episode"
        else state.step
    )
    limit = deps.config.budget.max_total_actions if layer == "run" else state.actions_budget
    if limit is not None and used >= limit:
        return Termination.ACTIONS_EXHAUSTED
    if state.done:
        return None
    if layer == "episode" and state.step >= deps.config.budget.episode_max_tasks:
        return Termination.TASKS_EXHAUSTED
    if layer == "run" and source in ("review_and_judge", "plan_run", "act"):
        if state.fail_streak >= deps.config.loop.run_stall_limit:
            return Termination.STALLED
        if state.step >= deps.config.budget.max_episodes:
            return Termination.BUDGET_EXHAUSTED
    return None


def stopped_updates(
    state: RunState | EpisodeRunState | TaskState,
    deps: RunRuntime | EpisodeRuntime | TaskRuntime,
    layer: str,
    source: str,
    term: Termination,
) -> dict[str, Any]:
    """机械停机与盖章全部记账，不再调用模型、人审或视觉感知。"""
    meta = budget_meta(state, layer, source)
    record_budget(deps.trace, meta, TraceKind.BUDGET_SKIPPED, reason=term.value, node=source)
    updates = settle_running(state, deps, layer, term)
    record_verdict(deps.trace, **meta, termination=term, judge_reason=term.value)
    return {**updates, "termination": term, "judge_reason": term.value}


def guarded(
    node: Callable[..., dict[str, Any]],
    layer: str,
    source: str,
    absorb: Callable[..., dict[str, Any]] | None = None,
) -> Callable[..., dict[str, Any]]:
    """包装普通节点；活对象只从 runtime 取，所有可恢复额度都在 state 里。"""

    def invoke(
        state: RunState | EpisodeRunState | TaskState,
        runtime: Runtime[RunRuntime | EpisodeRuntime | TaskRuntime],
    ) -> dict[str, Any]:
        deps = runtime.context
        updates = absorb(state, runtime) if absorb is not None else {}
        current = state.model_copy(update=updates)
        if deps.deadline is not None:
            deps.deadline.cap_remaining(current.remaining_s)
            current = current.model_copy(update={"remaining_s": deps.deadline.remaining()})
        term = budget_reason(current, deps, layer, source)
        finish = False
        if term is not None:
            updates.update(stopped_updates(current, deps, layer, source, term))
            finish = source.endswith("_done")
        elif not current.done or source.endswith("_done"):
            try:
                updates.update(node(current, runtime))
            except BudgetExhausted as exc:
                if exc.calls:
                    deps.trace.append(
                        FromHarnessToTraceToolAppendReq(
                            kind=_CALL_KINDS[exc.source],
                            meta=budget_meta(current, layer, source),
                            calls=list(exc.calls),
                        )
                    )
                updates.update(
                    stopped_updates(current, deps, layer, source, Termination.TIME_EXHAUSTED)
                )
                finish = source.endswith("_done")
        if finish:
            final = current.model_copy(update=updates)
            updates.update(node(final, runtime))
        if deps.deadline is not None:
            updates["remaining_s"] = deps.deadline.remaining()
        return updates

    return invoke
