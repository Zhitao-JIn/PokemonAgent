"""`plan`：**目标表的唯一写入点**——问 `Planner` 要一版规划，给人看一眼（插话），落表。

四件事，顺序固定：

1. **取素材**：从**记忆**里取本 run 的局索引与预取详情（`episode_memory`）、
   地图交互事实（`object_memory`），连同当前目标表装成 `PlannerContext`。
2. **要一版**：`Planner.plan(ctx)` 给出**未落表**的 `PlannerOutcome`——新增条目、
   对已有条目的定点更新、收手判定。默认实现是模型（`BrainPlanner`），
   也可以是人（`ConsolePlanner`）或什么都不做（`NullPlanner`）。
3. **给人看这一版**（**插话**）：`Reviewer.inject()` 亮出刚拿到的那一版 + 当前表；
   人若说了什么，**带着那句话再要一版**（重问 `Planner`，次数不限），
   直到人说"没意见"（空串）为止。
4. **落表**：先把 `updates` 逐条盖到对应条目上，再把 `entries` append 进表尾。

**为什么"插话"落在这里而不是落成一格**：加图节点要付 `recursion_limit` 的代价
（见 `docs/PLAN_console_reviewer.md` §3.2），所以插话一律是**节点内的同步函数调用**。

**0914 S2：素材从 trace 换成 memory。** 原先第 1 步读的是
`deps.trace.read_events()` 的全量事件流，`run_plan.py::history_lines` 再从里面折出
"每局一行"。那条路的毛病有二：与"存下来的东西只有 memory"相矛盾；trace 大半是
prompt/raw 噪声。现在读的是记忆——**trace 与 plan 之间不再有数据通路**。

**`auto_push_goals=False` 时根本不问 planner**：这一版注定不加新目标、也不改已有
条目，花一次模型调用是纯浪费。无头核对脚本（`check_harness.py`）走的就是这条路。

**`auto_decide_done=False` 时模型不能提前喊停**：模型说 `done` 只在那条开关为真时
生效；表末检（表里没有活跃条目 + 这一版不新增）**无条件生效**——它是这张图能停机的
前提，不能由开关关掉（关掉它就会路由到一条没有 `PENDING` 的表上，`dispatch` 当场断言失败）。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import (
    FromHarnessToMemoryToolQueryEpisodeSummariesReq,
    FromHarnessToMemoryToolQueryObjectEventsReq,
    FromHarnessToReviewerInjectReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.harness.domain import GoalEntry
from pokemon_agent.schemas.memory import EpisodeMemory

from ...deps import HarnessDeps
from ...interface.planner_context import PlannerContext
from ...interface.planner_outcome import ALLOWED_UPDATE_STATUSES, GoalUpdate, PlannerOutcome
from ..run_state import RunState


def plan(state: RunState, runtime: Runtime[HarnessDeps]) -> dict[str, Any]:
    """要一版规划 → 给人插话（不满意就带话重问）→ 应用更新 + 落表 → 表末检。

    前置条件：无（首次进图时表里只有初始条目；后续每轮进来是"上一局刚审完"）。
    后置条件：`state.plan` 是**原表 + 这一版的定点更新 + 这一版采纳的新条目**；
        没被点名的条目逐条不改；新条目一律 `PENDING`。

    后置条件（记账）：恰好多一条 `PLAN_VERDICT`。若判 done，`done=True` 且
        `why` 有值——"没有活可干"或"模型判定该收手"。
    """
    deps = runtime.context

    # 步骤 1–3：要一版（含插话循环）。`auto_push_goals=False` 时跳过——见模块 docstring。
    outcome = _elicit(deps, state) if deps.auto_push_goals else PlannerOutcome()

    # 步骤 4：应用定点更新 → 追加新条目。
    accepted = outcome.entries
    table = _apply_updates(state.plan, outcome.updates) + accepted

    # 表末检（`docs/PLAN_console_reviewer.md` §4.3）：
    #   表里没有任何 `PENDING`/`RUNNING` 条目 **且** 这一版不新增 → 判 done；
    # 外加**模型提前喊停**：`done=True` 且开关允许——"我判断剩下的不值得做"。
    #
    # `PENDING`/`RUNNING` 是"后面还要做的"；`COMPLETED`/`FAILED`/`ABANDONED` 都已出局
    # （留在表里当上下文与教训）。所以"表非空"不等于"还有活干"——一局跑成之后表是
    # "非空但没活"，这时要判 done，否则 `review → plan → review` 会转圈。
    has_work = any(entry.status.is_active for entry in table)
    model_done = outcome.done is True and deps.auto_decide_done
    if (not has_work and not accepted) or model_done:
        why = outcome.why or "表里没有待做目标，planner 也没有给出新的"
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.PLAN_VERDICT,
                meta={"source": "plan", "episode_id": state.run_id, "step": 0},
                done=True,
                pushed=[],
                why=why,
                input=outcome.input,
                output=outcome.output,
            )
        )
        return {"plan": table, "done": True, "why": why}

    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.PLAN_VERDICT,
            meta={"source": "plan", "episode_id": state.run_id, "step": 0},
            done=False,
            pushed=[entry.task.goal for entry in accepted],
            why=outcome.why or "planner 给出的这一版没有新目标",
            input=outcome.input,
            output=outcome.output,
        )
    )
    return {"plan": table}


def _elicit(deps: HarnessDeps, state: RunState) -> PlannerOutcome:
    """问 `Planner` 要一版，把人不满意的部分通过**插话**反馈回去，直到人满意。

    **为什么是循环而不是一次**：插话的语义是"我对这一版有意见"，人不满意就
    再说一句——`Planner` 带着累积的反馈重新出一版。次数不设上限（用户定调：
    不设）。人的"没意见"由 `inject()` 返回空串表达，循环就此结束。
    """
    feedback = ""
    while True:
        proposed = deps.planner.plan(_context(deps, state))
        note = deps.reviewer.inject(
            FromHarnessToReviewerInjectReq(
                prompt=_prompt_for(proposed, feedback),
                form=proposed,
                form_kind="PlannerOutcome",
            )
        )
        if not note:
            return proposed
        feedback = note


def _context(deps: HarnessDeps, state: RunState) -> PlannerContext:
    """从**记忆**里取这一版的规划素材。

    三段：本 run 的局索引（`episode_memory` 全量，**按执行顺序**）、
    其中几局的正文（一期规则见 `_pick_details`）、地图交互事实（`object_memory`）。

    **排序用 `state.outcomes` 而不是 `episode_id`**（0914 S2 的一个坑）：
    读口返回的顺序是 `episode_id` 字典序，而 `episode_id` 是 `{run_id}-ep{n}`
    ——`ep10 < ep2`，第 10 局之后顺序就乱了。`outcomes` 是按执行序 append 的
    机械记录，本来就准，不必从字符串里反解执行序。
    """
    summaries = deps.memory.query_episode_summaries(
        FromHarnessToMemoryToolQueryEpisodeSummariesReq(conditions={"run_id": state.run_id})
    ).summaries
    index = _in_execution_order(summaries, state.outcomes)
    objects = deps.memory.query_object_events(FromHarnessToMemoryToolQueryObjectEventsReq()).events
    return PlannerContext(
        run_id=state.run_id,
        plan=state.plan,
        index=index,
        details=_pick_details(index),
        objects=objects,
    )


def _in_execution_order(summaries: list[EpisodeMemory], outcomes: list) -> list[EpisodeMemory]:
    """按**执行顺序**排好局索引。

    排序键取 `state.outcomes` 里的下标（执行序 append 的机械记录）；没有对应
    outcome 的摘要（理论上不该有——记忆是这一局的产物）排在最后，按 `episode_id`
    兜底，保证顺序仍然确定（两次读拿到同一个序）。
    """
    order = {outcome.episode_id: i for i, outcome in enumerate(outcomes)}
    return sorted(
        summaries,
        key=lambda memory: (order.get(memory.episode_id, len(order)), memory.episode_id),
    )


def _pick_details(index: list[EpisodeMemory]) -> list[EpisodeMemory]:
    """一期详情预取规则：**最近 1 局 + 全部失败局**。

    这是渐进披露的最小可用形态——上下文里装"全部局的骨架 + 少数几局的肉"，
    而不是"把所有局的正文都倒进去"。三条依据：

    - **最近 1 局**：刚发生的事最相关，模型规划下一步时最先要看它；
    - **全部失败局**：失败是最该被看见的原料，"这个做法不行"必须能传到下一版规划里；
    - 其余（更早的成功局）：只给索引行——它们的内容多半已经被后续局覆盖。

    二期上工具环（模型自己请求要哪几局的正文）之后，这个函数退休，
    `details` 由模型的请求决定（信封不用改）。
    """
    chosen = {memory.episode_id for memory in index if not memory.success}
    if index:
        chosen.add(index[-1].episode_id)
    return [memory for memory in index if memory.episode_id in chosen]


def _apply_updates(plan: list[GoalEntry], updates: list[GoalUpdate]) -> list[GoalEntry]:
    """把模型对已有条目的表态逐条盖到表上（**定点更新**，不重写整表）。

    前置条件（`Planner` 实现保证）：每条 `update.status` 都在
        `ALLOWED_UPDATE_STATUSES` 里——只有"重开"（`PENDING`）与"放弃"（`ABANDONED`）
        两个值。`COMPLETED`/`FAILED` 是机械事实，只能由 harness 从这一局的结算推导
        （`review._stamp`），任何 planner 实现都不许代笔。
    后置条件：返回新表；点不到的表内条目（`task_id` 不存在）**跳过**——模型数错
        不是异常，只是那条表态作废；未被点名的条目逐字不动。
    """
    if not updates:
        return plan
    index_of = {entry.task.task_id: i for i, entry in enumerate(plan)}
    table = list(plan)
    for update in updates:
        assert update.status in ALLOWED_UPDATE_STATUSES, (
            f"planner 想写机械事实 {update.status!r}——那是 harness 的盖章地盘"
        )
        position = index_of.get(update.task_id)
        if position is None:
            continue
        entry = table[position]
        table[position] = entry.model_copy(
            update={
                "status": update.status,
                # 新理由优先；模型没给就留着上一条（上次失败/放弃的原因也是信息）。
                "note": update.note or entry.note,
            }
        )
    return table


def _prompt_for(proposed: PlannerOutcome, feedback: str) -> str:
    """给插话那一屏写说明文本。

    `feedback` 非空 = **这是重问**，把那句话原样再亮一次——人写的话在控制台上
    得看得见，否则"我说过什么"要靠记忆。
    """
    parts = []
    if proposed.entries:
        parts.append(f"planner 给出 {len(proposed.entries)} 条新目标")
    if proposed.updates:
        parts.append(f"并改动 {len(proposed.updates)} 条已有目标的状态")
    base = "；".join(parts) if parts else "planner 这一版没有新目标、也没改任何条目"
    if feedback:
        return f"{base}；上一轮你的意见：{feedback}"
    return base


__all__ = ["plan"]
