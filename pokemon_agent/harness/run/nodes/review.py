"""`review`：**h-in-the-loop 的落点 + 目标表的盖章台**——`reflect` 已并入这里。

一个 episode 跑完后（正常结算，或 `episode_error_handler` 兜出来的失败结算），
流程走到这一格。本节点做四件事，**顺序不能换**：

1. **收结算**：把 `state.outcome` 累积进 `outcomes`（原 `reflect` 的第一件事）；
2. **盖章**（机械）：按 `outcome.success` 把那条 `RUNNING` 目标改成
   `COMPLETED`（成功）或 `FAILED`（失败，**终态、不自动重派**）；
   `last_episode_id` 记下这一局的指针；
3. **审**（人的表态）：把刚才那份机械裁定亮给人（`Reviewer.audit`）。
   人**认账** → 2 的结果就定案；人**推翻** → 由 harness 重新盖章：
   成功改判失败（盖 `FAILED`）、失败改判成功（盖 `COMPLETED`）。
4. **补章**（0914 S3）：这一局若在 `episode_memory` 里没有任何记录，补一张
   **只有来源章**的（`_leave_chapter`）——保证"一局一条"，让跑挂的局
   在记忆里也留痕、`plan` 读得到。

**为什么"收结算"不能搬去别处**：`state.outcome` 是**单轮**字段（每一步都会被
下一轮覆盖），累积进跨轮的 `outcomes` 必须发生在"这一轮结束、下一轮开始之前"。
`review` 就是那个位置。

**为什么盖章要先于审**：给人看的那句话（"这一局算成/算败"）本来就得先有裁定
才有得看。先斩后奏的顺序也让人看到的是**机械事实**，而不是被人话带偏的东西。

**失败为什么盖 `FAILED` 而不是置回 `PENDING`**（这是本节点最容易被改错的一处）：
`review` 的出口无条件回 `plan`，而 `plan` 的表末检判据是"表里没有活跃条目 +
planner 不新增 → done"。若失败置回 `PENDING`（**活跃**），那条判据就永远不成立，
`review → plan → dispatch → review` 会**无限派发一条必败目标**（实测复现过）。
置 `FAILED`（**非活跃**）之后：

- 无头（`NullPlanner`）：没人重开 → 表末检成立 → done → 停机，
  正是 §6/§8-Q2 已确认的"零重试预算：一个目标只跑一局"；
- 有人/有模型：`Planner` 读表、**显式**把 `FAILED` 的条目重开成 `PENDING`，
  `plan` 出口才会再派——**重试因此真的是 plan 的决策，不是自动动作**。

**"重试"不再是人的选项**：旧的 `HumanDecision.RETRY` 已随槽机制删除。要重开一个
失败目标，正确做法是在 `plan` 节点里让 `Planner` 把它置回 `PENDING`
（`GoalStatus` 上唯一的"重开"迁移）。

**"停止"也不再是人的选项**：run 什么时候结束由**表末检**回答（表里没有活跃条目
且 planner 不新增）。人若想砍掉剩下的目标，正确做法是在 `plan` 节点里下
`ABANDONED`——那是 `GoalStatus` 上唯一人能直接写的状态。

**`episode_trace_events` 仍住本文件**：它唯一的调用点就是本节点（"把刚跑完那一局的
完整 trace 塞进审请求"）。
"""

from __future__ import annotations

import json
from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import (
    AuditVerdict,
    FromHarnessToMemoryToolQueryEpisodeSummariesReq,
    FromHarnessToMemoryToolStoreEpisodeSummaryReq,
    FromHarnessToReviewerAuditReq,
    FromHarnessToTraceToolAppendReq,
    FromRunHarnessToEpisodeHarnessRunResp,
    TraceEvent,
    TraceKind,
)
from pokemon_agent.schemas.harness.domain import GoalEntry, GoalStatus
from pokemon_agent.schemas.memory import EpisodeMemory

from ...deps import HarnessDeps
from ..run_state import RunState


def episode_trace_events(events: list[TraceEvent], episode_id: str) -> list[TraceEvent]:
    """从全量事件流里挑出单个 episode 的完整 trace（`events` 已按 `(ts, uuid)`
    升序，见 `TraceToolPort.read_events`，这里原序保留）。

    **`episode_id` 住在 `meta` 里**（0914 封套改造后顶层不再有那个字段），
    所以筛选要先把 `meta` 那串 JSON 解回来；解不动的事件跳过（残文件是预期内的）。

    `read_events()` 自己就支持按局切片，但本节点要的是"**先把完整 trace 装进
    请求**、再按局筛出来"这份语义（同一个 `req.episode_trace` 字段，将来若改
    成带别局上下文时改这一处即可），所以筛选留在这里而不是传参给读口。
    """
    return [ev for ev in events if _meta_episode_id(ev) == episode_id]


def _meta_episode_id(event: TraceEvent) -> str:
    """从事件的 `meta` JSON 里取 `episode_id`；读不动给空串。

    与 `trace.store._episode_id` 同形但**不共用**：那个在 trace 内部（harness 不
    import `pokemon_agent.trace` 的实现），各写各的。`meta` 里的键是 harness 自己
    装进去的，所以由 harness 解回来是它分内的事。
    """
    try:
        meta = json.loads(event.meta)
    except (json.JSONDecodeError, TypeError):
        return ""
    return str(meta.get("episode_id", "")) if isinstance(meta, dict) else ""


def review(state: RunState, runtime: Runtime[HarnessDeps]) -> dict[str, Any]:
    """收结算 → 按裁定盖章 → 亮给人审 → 按人的表态定案 → 给这一局补记忆章。

    前置条件：`state.outcome` 非空（`episode` 或 `episode_error_handler` 写的），
        且表里恰有一条 `RUNNING`。
    后置条件：返回后 `outcomes` 多一条结算；那条目标已定案（`COMPLETED` 或
        `FAILED`，**都是非活跃终态**）；至多一条 `RUNNING`（本节点必把它清掉，
        所以是**零条**）；这一局在 `episode_memory` 里**恰好一条**记录
        （已有则不动，没有则补一张只有来源章的，见 `_leave_chapter`）。

    依赖从 `runtime.context` 取：`reviewer` 是"人和图之间的那扇门"，必须是
    **装配时注入的那个实例**。

    历史读的是**磁盘账本**（`deps.trace.read_events()`）——0913 晚 `RunDataCenter`
    的内存事件镜像删除后，盘上那份就是唯一真相。
    """
    deps = runtime.context
    assert state.outcome is not None, "review() without a fresh outcome"

    outcome = state.outcome
    index = _running_index(state.plan)
    assert index is not None, "review() found no RUNNING goal to stamp"
    entry = state.plan[index]

    # 步骤 1 + 2：先机械盖章（成功 → COMPLETED；失败 → 置回 PENDING）。
    stamped = _stamp(entry, outcome.success, outcome.episode_id)

    # 步骤 3：把这份裁定亮给人。
    episode_trace = (
        episode_trace_events(deps.trace.read_events(), state.episode_id) if state.episode_id else []
    )
    resp = deps.reviewer.audit(
        FromHarnessToReviewerAuditReq(
            run_id=state.run_id,
            episode_id=state.episode_id or "",
            outcome=outcome,
            episode_trace=episode_trace,
        )
    )

    # 人推翻 → harness 重新盖章（盖的是反面）；同时把纠正理由记进 note，
    # 它会随目标表一路带到后续 prompt 的**最末尾**。
    if resp.verdict is AuditVerdict.OVERTURN:
        stamped = _stamp(entry, not outcome.success, outcome.episode_id)
        if resp.note:
            stamped = stamped.model_copy(update={"note": resp.note})

    plan = state.plan[:index] + [stamped] + state.plan[index + 1 :]
    _leave_chapter(deps, state.run_id, stamped, outcome)
    return {
        "plan": plan,
        "outcomes": state.outcomes + [outcome],
    }


_CHAPTER_RATIONALE = "本局没有产出可蒸馏的正文（整局异常，或收尾时没有一条可信的 step 记忆）"
"""空正文记录写进 `quality_rationale` 的那句话——它是这一条唯一说得出的内容。"""


def _leave_chapter(
    deps: HarnessDeps,
    run_id: str,
    entry: GoalEntry,
    outcome: FromRunHarnessToEpisodeHarnessRunResp,
) -> None:
    """保证 **"一局一条"**：这一局若在记忆里没有任何记录，补一张只有来源章的。

    **为什么写在 `review`**（0914 S3）：它是**唯一每局必过**的地方——正常局走
    `episode → review`，异常局走 `episode_error_handler → review`。收尾链自己
    补不齐：异常局根本没进子图（handler 拿不到 runtime，写不了记忆）；
    "没有可信 step 记忆"那支虽在子图里，但"这一局到底留没留下东西"
    只有跑完才知道。

    **先查再写**：正常局已经在 `verify_and_summarize` 里落过一条带正文的记录，
    这里查到就什么都不做——补的这条只填**空缺**，不覆盖已有的正文。

    **已知边界**：人推翻 judge 裁决（`OVERTURN`）时，已有那条记录的 `success`
    章不会跟着改（它盖的是子图当时的判定）。这是"收尾"与"审判"之间的时序问题，
    与"一局一条"无关，留作单独的账。

    前置条件：`outcome.episode_id` 非空。
    后置条件：返回后**要么**本来就有一条，**要么**多了一条**正文全空**的记录，
        并记了一条 `write_episode`。
    """
    episode_id = outcome.episode_id
    assert episode_id, "_leave_chapter() needs a non-empty episode_id"
    existing = deps.memory.query_episode_summaries(
        FromHarnessToMemoryToolQueryEpisodeSummariesReq(conditions={"episode_id": episode_id})
    ).summaries
    if existing:
        return
    chapter = EpisodeMemory(
        episode_id=episode_id,
        run_id=run_id,
        goal=entry.task.goal,
        success=entry.status is GoalStatus.COMPLETED,
        steps=outcome.steps,
        summary="",
        quality_score=0.0,
        quality_rationale=_CHAPTER_RATIONALE,
    )
    stored = deps.memory.store_episode_summary(
        FromHarnessToMemoryToolStoreEpisodeSummaryReq(memory=chapter)
    ).memory
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.WRITE_EPISODE,
            meta={"source": "review", "episode_id": episode_id, "step": outcome.steps},
            # 与 `verify_and_summarize` 那条**逐字同形**，只有 `source` 不同：
            # 这条是空章版，账上分得开才看得出"这一局没正文"是被谁写下来的。
            memory=stored,
        )
    )


def _running_index(plan: list[GoalEntry]) -> int | None:
    """表里那条 `RUNNING` 的下标；没有则 `None`。"""
    return next(
        (i for i, entry in enumerate(plan) if entry.status is GoalStatus.RUNNING),
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

    - headless（`NullPlanner`，§6/§8-Q2）：没人重开 → 表末检成立 → 判 done → 停机。
      这正是用户已确认接受的"零重试预算：一个目标只跑一局"；
    - 有人/有模型：`Planner` 读表看见 `FAILED` 的条目，**显式**把它重开成
      `PENDING`（`GoalStatus` 上唯一的"重开"迁移），`plan` 出口才会再派一局。

    也就是说 `FAILED` **不是"放弃"**（放弃是 `ABANDONED`），它只是"这一局没过、
    停在终态、等下一轮 plan 表态"。（`docs/PLAN_console_reviewer.md` §4.3 的
    权限表把它写成"人审时表态放弃"，这里是实现口径的收口：失败默认落 `FAILED`，
    重开由 plan 做；两者一致——都是"失败不再自动重试"。）

    `last_episode_id` 两种情况都写——它是"这个状态从哪看来的"的追溯键，
    没有来源的状态等于不可追溯的断言（见 `GoalEntry.last_episode_id` 的说明）。
    """
    return entry.model_copy(
        update={
            "status": GoalStatus.COMPLETED if success else GoalStatus.FAILED,
            "last_episode_id": episode_id,
        }
    )


__all__ = ["episode_trace_events", "review"]
