"""两层规划的纯状态表变换与图路由；不调用模型或世界。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, TypeVar

from pokemon_agent.brain.interface import Decomposition, RunPlan
from pokemon_agent.direct.planning_validation import pending_references
from pokemon_agent.schemas.harness.domain import EntryStatus, GoalEntry, TaskEntry

if TYPE_CHECKING:
    from .episode.episode_state import EpisodeRunState
    from .run.run_state import RunState

Entry = TypeVar("Entry", GoalEntry, TaskEntry)


def entry_identity(entry: GoalEntry | TaskEntry) -> str:
    """逻辑目标身份；L2 不使用本次执行 task_id。"""
    return entry.entry_id if isinstance(entry, TaskEntry) else entry.task.task_id


def apply_planning(
    table: Sequence[Entry],
    new_entries: Sequence[Entry],
    proposal: RunPlan | Decomposition,
    previous_order: Sequence[str],
) -> tuple[list[Entry], list[str]]:
    """验证后原子生成新表及稳定身份顺序；输入不变，非法提案抛 ValueError。"""
    assert all(change.status in ("pending", "abandoned") for change in proposal.updates)
    refs = pending_references(proposal, [entry.status.value for entry in table])
    updated = list(table)
    for change in proposal.updates:
        updated[change.index] = updated[change.index].model_copy(
            update={"status": EntryStatus(change.status), "note": change.note}
        )
    combined = [*updated, *new_entries]
    lookup = {f"existing:{i}": entry_identity(e) for i, e in enumerate(updated)}
    lookup.update({f"new:{i}": entry_identity(e) for i, e in enumerate(new_entries)})
    order = [lookup[ref] for ref in refs]
    if proposal.execution_order is None:
        retained = [identity for identity in previous_order if identity in order]
        order = [*retained, *(identity for identity in order if identity not in retained)]
    return combined, order


def dispatch_index(table: Sequence[GoalEntry | TaskEntry], order: Sequence[str]) -> int:
    """调用方保证存在待办、无运行条目；优先按保存的派发顺序选择。"""
    assert not any(entry.status is EntryStatus.RUNNING for entry in table)
    pending = {entry_identity(e): i for i, e in enumerate(table) if e.status is EntryStatus.PENDING}
    assert pending, "dispatch without PENDING entry"
    return next((pending[item] for item in order if item in pending), next(iter(pending.values())))


def planning_route(state: RunState | EpisodeRunState, table_name: str, finish: str) -> str:
    """规划后的条件边；无待办回 judge，不进入 act。"""
    if state.done:
        return finish
    return (
        "act"
        if any(e.status is EntryStatus.PENDING for e in getattr(state, table_name))
        else "review_and_judge"
    )
