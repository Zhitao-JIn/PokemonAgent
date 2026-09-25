"""`review_and_judge` 格（run 层）：**收结算 + 判停**——run 唯一的停机判定点。

1. 定案上一局（表里有 RUNNING 时）：按 `success` 盖章（成功 COMPLETED / 失败 FAILED，
   都是终态、不自动重派）→ 亮给人审，推翻则盖反面、`overturned=True`、修正 `fail_streak`
   → 记 `settle_goal`。（一局一条 EpisodeMemory 由 episode 层自己保证，本格不写记忆。）
   （收结算在 perceive 的 `absorb_episode`。）
2. 机械三类：上一局终局帧 `obs.done` / `fail_streak >= RUN_STALL_LIMIT` /
   `step >= RUN_MAX_EPISODES`。
3. 问模型"run_goal 达成没有"（素材是 `plan_ctx.index` 局摘要），判成即 `GOAL_DONE`。

失败盖 FAILED 而非 PENDING：要不要重试是 `plan_run` 的决策（它可以把 FAILED 重开）。
"""

from __future__ import annotations

import json
from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.config import RUN_MAX_EPISODES, RUN_STALL_LIMIT
from pokemon_agent.schemas.harness import (
    AuditVerdict,
    FromHarnessToBrainToolJudgeReq,
    FromHarnessToReviewerAuditReq,
    FromHarnessToTraceToolAppendReq,
    TraceEvent,
    TraceKind,
)
from pokemon_agent.schemas.harness.domain import EntryStatus, EpisodeOutput, GoalEntry, Termination

from ...judging import ask_judger, judge_reason, mechanical_termination, record_verdict
from ...reviewing import ask_audit
from ..run_state import RunState
from ..runtime import RunRuntime

_SOURCE = "run.review_and_judge"


def episode_trace_events(events: list[TraceEvent], episode_id: str) -> list[TraceEvent]:
    """从全量事件流里挑出单个 episode 的完整 trace（`events` 已按 `(ts, uuid)`
    升序，见 `TraceToolPort.read_events`，这里原序保留）。

    **`episode_id` 住在 `meta` 里**（0914 封套改造后顶层不再有那个字段），
    所以筛选要先把 `meta` 那串 JSON 解回来；解不动的事件跳过（残文件是预期内的）。

    `read_events()` 自己就支持按签名筛选，但本节点要的是"**先把整 run 的 trace
    装进请求**、再按局筛出来"这份语义（同一个 `req.episode_trace` 字段，将来若改
    成带别局上下文时改这一处即可），所以筛选留在这里而不是传参给读口——
    调用点传给读口的是 `{"run_id": …}`（落盘不按 run 分层，得自己把范围圈到本 run）。
    """
    return [ev for ev in events if _meta_episode_id(ev) == episode_id]


def _meta_episode_id(event: TraceEvent) -> str:
    """从事件的 `meta` JSON 里取 `episode_id`；读不动给空串。

    与 `trace.store._meta_of` 同形但**不共用**：那个在 trace 内部（harness 不
    import `pokemon_agent.trace` 的实现），各写各的。`meta` 里的键是 harness 自己
    装进去的，所以由 harness 解回来是它分内的事。
    """
    try:
        meta = json.loads(event.meta)
    except (json.JSONDecodeError, TypeError):
        return ""
    return str(meta.get("episode_id", "")) if isinstance(meta, dict) else ""


def review_and_judge(state: RunState, runtime: Runtime[RunRuntime]) -> dict[str, Any]:
    """定案上一局（盖章 → 人审）→ 机械三类 + 问模型，写 `termination`。

    上一局的结算已由 `perceive` 收进 `episode_outputs`（与 episode / task 两层同构：吸收在
    perceive、判定在这里）。表里有 `RUNNING` 就说明刚跑完一局，用 `outcomes[-1]` 定案。
    """
    deps = runtime.context
    updates: dict[str, Any] = {}

    # 步骤 1：刚跑完一局就定案那条 RUNNING（首圈没有）。
    if _running_index(state.goals) is not None:
        updates = _settle(deps, state, state.episode_outputs[-1])
    fail_streak = updates.get("fail_streak", state.fail_streak)
    last = state.episode_outputs[-1] if state.episode_outputs else None

    # 步骤 2：机械三类；还没跑过局时不问模型。
    termination = mechanical_termination(
        world_ended=bool(last and last.observation and last.observation.done),
        stalled=fail_streak >= RUN_STALL_LIMIT,
        exhausted=state.step >= RUN_MAX_EPISODES,
    )
    verdict = None

    # 步骤 3：问模型"run_goal 达成没有"（素材是本 run 的局摘要），判成覆盖机械结论。
    if last is not None:
        index = state.plan_ctx.index if state.plan_ctx is not None else []
        verdict = ask_judger(
            deps.judger,
            deps.trace,
            FromHarnessToBrainToolJudgeReq(goal=state.run_goal, episode_memories=index),
            source=_SOURCE,
            episode_id=state.run_id,
            task_id=state.run_id,
            step=state.step,
        )
        if verdict.done:
            termination = Termination.GOAL_DONE

    # 步骤 4：记结论。
    reason_for_judge = judge_reason(termination, verdict, not_asked="还没跑过局，不问模型")
    record_verdict(
        deps.trace,
        source=_SOURCE,
        episode_id=state.run_id,
        task_id=state.run_id,
        step=state.step,
        termination=termination,
        judge_reason=reason_for_judge,
        fail_streak=fail_streak,
        verdict=verdict,
    )
    return {**updates, "termination": termination, "judge_reason": reason_for_judge}


def _settle(deps: RunRuntime, state: RunState, outcome: EpisodeOutput) -> dict[str, Any]:
    """盖章 → 亮给人审（推翻则盖反面、修正 `fail_streak`）→ 记 `settle_goal`。"""
    index = _running_index(state.goals)
    assert index is not None, "review_and_judge found no RUNNING goal to stamp"
    assert outcome.goal_id == state.goals[index].task.task_id, "最新结算与 RUNNING 条目对不上"
    entry = state.goals[index]

    # 步骤 1：机械盖章。
    stamped = _stamp(entry, outcome.success, outcome.episode_id)

    # 步骤 2：亮给人审；推翻则盖反面，理由记进 note，失败连击跟着修正。
    resp = ask_audit(
        deps.reviewer,
        deps.trace,
        FromHarnessToReviewerAuditReq(
            run_id=state.run_id,
            episode_id=outcome.episode_id,
            outcome=outcome,
            events=episode_trace_events(
                deps.trace.read_events({"run_id": state.run_id}), outcome.episode_id
            ),
        ),
        meta={
            "source": _SOURCE,
            "episode_id": state.run_id,
            "task_id": state.run_id,
            "step": state.step,
        },
    )
    fail_streak = state.fail_streak
    if resp.verdict is AuditVerdict.OVERTURN:
        stamped = _stamp(entry, not outcome.success, outcome.episode_id).model_copy(
            update={"overturned": True, "note": resp.note or stamped.note}
        )
        fail_streak = 0 if stamped.status is EntryStatus.COMPLETED else fail_streak + 1

    # 步骤 3：记定案账。
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.SETTLE_GOAL,
            meta={
                "source": _SOURCE,
                "episode_id": state.run_id,
                "task_id": state.run_id,
                "step": state.step,
            },
            goal=stamped,
            audit=resp.verdict.value,
            fail_streak=fail_streak,
        )
    )
    return {
        "goals": [*state.goals[:index], stamped, *state.goals[index + 1 :]],
        "fail_streak": fail_streak,
    }


def _running_index(plan: list[GoalEntry]) -> int | None:
    """表里那条 `RUNNING` 的下标；没有则 `None`。"""
    return next(
        (i for i, entry in enumerate(plan) if entry.status is EntryStatus.RUNNING),
        None,
    )


def _stamp(entry: GoalEntry, success: bool, episode_id: str) -> GoalEntry:
    """把一局的结果盖到目标上——**机械事实，只由 harness 调用**。

    `success=True`  → `COMPLETED`（终态，不再派发）；
    `success=False` → `FAILED`（**终态**，本局就是没过，且不再自动重派）。

    **为什么失败是 `FAILED` 而不是置回 `PENDING`**：这是"重试是 plan 的显式决定"
    这句定调能在图上停机的前提。若失败置回 `PENDING`，`PENDING` 是活跃状态，
    `plan` 的表末检就永远不成立 → `review → plan → dispatch → review` 死循环
    （实测：一条必败目标会把 episode 无限派下去）。置 `FAILED`（非活跃）之后：

    - headless：brain 的下一版规划不重开 → 表末检成立 → 判 done → 停机。
      这正是用户已确认接受的"零重试预算：一个目标只跑一局"；
    - 有人/有模型：`plan` 读表看见 `FAILED` 的条目，**显式**把它重开成
      `PENDING`（`EntryStatus` 上唯一的"重开"迁移），`plan` 出口才会再派一局。

    也就是说 `FAILED` **不是"放弃"**（放弃是 `ABANDONED`），它只是"这一局没过、
    停在终态、等下一轮 plan 表态"。（`docs/PLAN_console_reviewer.md` §4.3 的
    权限表把它写成"人审时表态放弃"，这里是实现口径的收口：失败默认落 `FAILED`，
    重开由 plan 做；两者一致——都是"失败不再自动重试"。）

    `last_episode_id` 两种情况都写——它是"这个状态从哪看来的"的追溯键，
    没有来源的状态等于不可追溯的断言（见 `GoalEntry.last_episode_id` 的说明）。
    """
    return entry.model_copy(
        update={
            "status": EntryStatus.COMPLETED if success else EntryStatus.FAILED,
            "last_episode_id": episode_id,
            "overturned": False,
        }
    )


__all__ = ["episode_trace_events", "review_and_judge"]
