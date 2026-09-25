"""`plan_run`：**目标表的唯一写入点**——问 planner 要一版规划，给人插话，落表。

1. 素材是 `perceive` 写好的 `plan_ctx`（局索引 + 详情 + 地图事实）连同当前目标表。
2. `planner.plan(req)` 交回 `RunPlan`（新目标 + 对已有条目的重开/放弃表态），
   `_to_outcome` 把它翻成 `PlannerOutcome`（表内序号 → `task_id`）。
3. `Reviewer.inject()` 亮出这一版；人说了话就带话重问，直到没意见。
4. 先盖定点更新、再追加新条目。

**停机不归本格**：只由 `review_and_judge` 判。规划完表里仍没有 PENDING 时抛
`NoGoalToDispatch`（fail-fast），而不是静默停机。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.brain import Task
from pokemon_agent.config import PLAN_MAX_NEW_GOALS
from pokemon_agent.errors import MaxRetriesExceeded, NoGoalToDispatch
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolPlanOnceReq,
    FromHarnessToBrainToolPlanOnceResp,
    FromHarnessToReviewerInjectReq,
    FromHarnessToTraceToolAppendReq,
    TraceKind,
)
from pokemon_agent.schemas.harness.domain import EntryStatus, GoalEntry

from ...interface.planner_outcome import ALLOWED_UPDATE_STATUSES, GoalUpdate, PlannerOutcome
from ...reviewing import ask_inject
from ..run_state import RunState
from ..runtime import RunRuntime


def plan_run(state: RunState, runtime: Runtime[RunRuntime]) -> dict[str, Any]:
    """要一版规划 → 给人插话（不满意就带话重问）→ 应用定点更新 + 追加新条目。

    后置条件：`state.goals` 是**原表 + 这一版的定点更新 + 这一版采纳的新条目**，
        且至少一条 `PENDING`；否则抛 `NoGoalToDispatch`（停机不归本格判）。
        每次问模型一条 `plan_call`，定稿一条 `plan_verdict`。
    """
    deps = runtime.context
    meta = {
        "source": "plan_run",
        "episode_id": state.run_id,
        "task_id": state.run_id,
        "step": state.step,
    }

    # 步骤 1：要一版（含插话循环）。
    outcome, note = _elicit(deps, state, meta)

    # 步骤 2：应用定点更新 → 追加新条目，记结论。
    table = _apply_updates(state.goals, outcome.updates) + outcome.entries
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.PLAN_VERDICT,
            meta=meta,
            pushed=[entry.task.goal for entry in outcome.entries],
            updates=[
                {"task_id": u.task_id, "status": u.status.value, "note": u.note}
                for u in outcome.updates
            ],
            why=outcome.why or "brain 这一版没有新目标",
            input=outcome.input,
            output=outcome.output,
            human_note=note,
        )
    )

    # 步骤 3：run 未判停就必须有活可派。
    if not any(entry.status is EntryStatus.PENDING for entry in table):
        raise NoGoalToDispatch("plan_run 之后目标表里没有 PENDING 条目")
    return {"goals": table}


def _elicit(deps: RunRuntime, state: RunState, meta: dict[str, Any]) -> tuple[PlannerOutcome, str]:
    """问 brain 要一版；人有意见就带着那句话重问，直到人没意见。返回 `(定稿, 定稿时的插话)`。"""
    ctx = state.plan_ctx
    assert ctx is not None, "plan_run before perceive"
    note = ""
    while True:
        req = FromHarnessToBrainToolPlanOnceReq(
            run_id=state.run_id,
            plan=state.goals,
            index=ctx.index,
            details=ctx.details,
            objects=ctx.objects,
            max_push=PLAN_MAX_NEW_GOALS,
            human_note=note,
        )
        proposed = _to_outcome(state.goals, state.run_id, _ask(deps, meta, req))
        reply = ask_inject(
            deps.reviewer,
            deps.trace,
            FromHarnessToReviewerInjectReq(
                prompt=_prompt_for(proposed, note),
                form=proposed,
                form_kind="PlannerOutcome",
            ),
            meta=meta,
        )
        if not reply:
            return proposed, note
        note = reply


def _ask(
    deps: RunRuntime, meta: dict[str, Any], req: FromHarnessToBrainToolPlanOnceReq
) -> FromHarnessToBrainToolPlanOnceResp:
    """问一次 planner 并记 `plan_call`；耗尽时记整条账 + `call_exhausted` 后上抛。"""
    try:
        resp = deps.planner.plan(req)
    except MaxRetriesExceeded as exc:
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.PLAN_CALL, meta=meta, calls=list(exc.calls)
            )
        )
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(kind=TraceKind.CALL_EXHAUSTED, meta=meta, link="plan")
        )
        raise
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(kind=TraceKind.PLAN_CALL, meta=meta, calls=resp.calls)
    )
    return resp


def _to_outcome(
    plan_table: list[GoalEntry],
    run_id: str,
    resp: FromHarnessToBrainToolPlanOnceResp,
) -> PlannerOutcome:
    """模型方言 → run 级编排方言（原 `BrainPlanner` 的翻译，随端口撤销搬到这里）。

    `RunPlan.PlanUpdate.index` 是**表内序号**（prompt 里 `[ ]` 那个），这里翻成
    `task_id`；越界（模型数错行）不是异常，只是那条表态作废。
    `entries` 的 `task_id` 由这里生成：形如 `plan-{run_id}-{n}`，接着表里已有的
    同前缀号往下数，并按条数递增 `offset`——一次推多条不会撞号。
    `input`/`output` 取自最后一次成功调用的账（给 `PLAN_VERDICT` 那条账供人看）。
    """
    run_plan = resp.plan
    entries = [
        GoalEntry(
            task=Task(
                task_id=_next_task_id(plan_table, run_id, offset),
                goal=plan_goal.goal,
                success_criteria=plan_goal.success_criteria,
                max_steps=plan_goal.max_steps,
            ),
            status=EntryStatus.PENDING,
        )
        for offset, plan_goal in enumerate(run_plan.push_goals)
    ]
    # 模型按**表内序号**指名（prompt 里 `[0]`/`[1]` 那个），这里翻译成 `task_id`
    # ——序号是"位置"，task_id 是"身份"，越界（模型数错行）就丢这条表态：
    # 数错不是异常，只是这条作废。
    updates = [
        GoalUpdate(
            task_id=plan_table[update.index].task.task_id,
            status=EntryStatus(update.status),
            note=update.note,
        )
        for update in run_plan.updates
        if 0 <= update.index < len(plan_table)
    ]
    return PlannerOutcome(
        entries=entries,
        updates=updates,
        why=run_plan.why,
        input=resp.calls[-1].payload.get("prompt", ""),
        output=resp.calls[-1].payload.get("raw", ""),
    )


def _next_task_id(plan: list[GoalEntry], run_id: str, offset: int) -> str:
    """给模型新拆出来的目标编一个表内唯一的 `task_id`。

    形如 `plan-{run_id}-{n}`，`n` 接着表里已有的 `plan-{run_id}-` 前缀往下数
    （不是"表长 + 1"——表里还有初始目标与人工写的目标，它们的 id 不带这个前缀，
    按表长数会在"删过/重开过"之后撞号）。
    """
    prefix = f"plan-{run_id}-"
    used = 0
    for entry in plan:
        task_id = entry.task.task_id
        if task_id.startswith(prefix) and task_id.removeprefix(prefix).isdigit():
            used = max(used, int(task_id.removeprefix(prefix)))
    return f"{prefix}{used + 1 + offset}"


def _apply_updates(plan: list[GoalEntry], updates: list[GoalUpdate]) -> list[GoalEntry]:
    """把 brain 对已有条目的表态逐条盖到表上（**定点更新**，不重写整表）。

    前置条件：每条 `update.status` 都在 `ALLOWED_UPDATE_STATUSES` 里——只有
        "重开"（`PENDING`）与"放弃"（`ABANDONED`）两个值。`COMPLETED`/`FAILED`
        是机械事实，只能由 harness 从这一局的结算推导（`review._stamp`）。
        正常路径下 `RunPlan.PlanUpdate.status` 的 Literal 已把这两值之外挡掉；
        这个断言是防 `model_construct` 绕过校验的 invariant，不是第二道输入校验。
    后置条件：返回新表；点不到的表内条目（`task_id` 不存在）**跳过**——模型数错
        不是异常，只是那条表态作废；未被点名的条目逐字不动。
    """
    if not updates:
        return plan
    index_of = {entry.task.task_id: i for i, entry in enumerate(plan)}
    table = list(plan)
    for update in updates:
        assert update.status in ALLOWED_UPDATE_STATUSES, (
            f"brain 想写机械事实 {update.status!r}——那是 harness 的盖章地盘"
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
        parts.append(f"brain 给出 {len(proposed.entries)} 条新目标")
    if proposed.updates:
        parts.append(f"并改动 {len(proposed.updates)} 条已有目标的状态")
    base = "；".join(parts) if parts else "brain 这一版没有新目标、也没改任何条目"
    if feedback:
        return f"{base}；上一轮你的意见：{feedback}"
    return base


__all__ = ["plan_run"]
