"""`RunResult` 的组装（plan2 R1/R2b）：usage / 机械计数 / 墙钟 / 逐局边界在收尾侧聚合。

聚合口径与 evals 侧 `efficiency()` 同构（分家：谁产出谁消费）——只统计**本执行线**
（`branch` 过滤，恢复线不重复计父线的账）；run 级账（`meta.episode_id == run_id`）
不进 `episode_bounds`。
"""

from __future__ import annotations

from pokemon_agent.direct.trace import MODEL_CALL_KINDS, parse
from pokemon_agent.direct.trace.content import ModelCallContent
from pokemon_agent.schemas.harness import TraceKind
from pokemon_agent.schemas.harness.domain import (
    EpisodeBound,
    LineCounts,
    LinkUse,
    RunResult,
    UsageSummary,
)


def line_events(raw: list, branch: str) -> list:
    """原始账封套 → 本执行线的 ParsedEvent（`parse` 是 tool 层读侧，259）。"""
    return [p for p in (parse(e) for e in raw) if p.meta.branch == branch]


def aggregate(
    events: list, *, run_id: str
) -> tuple[UsageSummary, LineCounts, float, float, list[EpisodeBound]]:
    """从本执行线的账聚合出 usage / 机械计数 / 墙钟 / 逐局边界。

    后置条件：无账时 usage、counts 全零，墙钟 (0.0, 0.0)，bounds 空——与"无产出"同形，不抛。
    """
    usage = UsageSummary()
    counts = LineCounts()
    bounds: dict[str, EpisodeBound] = {}
    starts: list[float] = []
    ends: list[float] = []
    for e in events:
        starts.append(e.started_at)
        ends.append(e.ended_at)
        eid = e.meta.episode_id
        if eid and eid != run_id:
            bound = bounds.setdefault(eid, EpisodeBound(episode_id=eid))
            if not bound.first_event:
                bound.first_event = e.uuid
            bound.last_event = e.uuid
        if e.kind in MODEL_CALL_KINDS:
            assert isinstance(e.content, ModelCallContent)
            link = e.kind.removesuffix("_call")
            use = usage.tokens_by_link.setdefault(link, LinkUse())
            use.input += e.content.input_tokens
            use.output += e.content.output_tokens
            use.cached += e.content.cached_tokens
            use.reasoning += e.content.reasoning_tokens
            usage.calls_by_link[link] = usage.calls_by_link.get(link, 0) + 1
        elif e.kind == TraceKind.CALL_FAILED:
            usage.call_failed += 1
        elif e.kind == TraceKind.CALL_EXHAUSTED:
            usage.call_exhausted += 1
        elif e.kind == TraceKind.ACT_CALL:
            counts.presses += 1
        elif e.kind == TraceKind.EPISODE_START:
            counts.episodes += 1
        elif e.kind == TraceKind.TASK_START:
            counts.tasks += 1
    return (
        usage,
        counts,
        min(starts) if starts else 0.0,
        max(ends) if ends else 0.0,
        list(bounds.values()),
    )


def build(
    *,
    run_id: str,
    sample_id: str,
    branch: str,
    termination: str,
    outcomes: list,
    total: int,
    succeeded: int,
    success_rate: float,
    raw_events: list,
) -> RunResult:
    """终态结算 + 本执行线账聚合 → `RunResult`（`close` 的实体）。"""
    usage, counts, started_at, ended_at, bounds = aggregate(
        line_events(raw_events, branch), run_id=run_id
    )
    return RunResult(
        run_id=run_id,
        sample_id=sample_id,
        branch=branch,
        termination=termination,
        outcomes=outcomes,
        total=total,
        succeeded=succeeded,
        success_rate=success_rate,
        started_at=started_at,
        ended_at=ended_at,
        usage=usage,
        counts=counts,
        episode_bounds=bounds,
    )


__all__ = ["aggregate", "build", "line_events"]
