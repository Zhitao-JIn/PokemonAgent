"""`BrainPlanner`：**模型侧**的 `Planner` 实现——把"给出一版规划"交给大脑。

**它解决什么问题**：run 图 `plan` 那一格原先只有人会做（`ConsolePlanner`），
于是目标表只由初始那批目标驱动。这个实现让模型读记忆（本 run 的局索引 + 详情 +
地图事实）与目标表，自己决定下一步该做什么——也就是
`docs/PLAN_planner_v2.md` 的 (a) 渐进披露 + (b) 状态化任务表。

**它是 harness 对 brain 的"翻译"发生在哪一层的问题**：`Brain.plan()` 的产出是
`RunPlan`（brain 的领域模型：`push_goals` / `done` / `why`，纯任务、无状态），
`Planner` 的产出是 `PlannerOutcome`（run 级编排词汇：`GoalEntry` 带 status）。
两边形状的搬运**只有这一处**——所以它虽然是 harness 的协议实现，
却要认识 brain 的形状。按铁律 2，这种"认识两边"的角色本该住 tool 层；
这里之所以例外，是因为 `Planner` 是**只在 harness 内部消费**的协议（run 图），
不跨模块边界——对外露出给实验层的仍然是 `Task`（`run_entry.initial_plan`）。

**`RunPlan.done` 的归宿**：模型说"该收手了"是有信息量的，但它**不是判决**——
真正判 done 的是 `plan` 节点的表末检（表里没有活跃条目 + 这一版不新增），
所以这里把 `done`/`why` 原样带上去，由 `plan` 节点自己决定怎么用
（模型说 done 但表里还有待做目标时，表末检说了算）。

**`task_id` 由这里生成**（`plan-{run_id}-{n}`）：`RunPlan.PlanGoal` 不带
`task_id`——run 级自主拆解的目标没有实验分组键（那是 `Task.task_id` 在实验层的
含义）。序号接着表里已有的同名条目往下数，重开一版也不会撞号。
"""

from __future__ import annotations

from pokemon_agent.brain import RunPlan, Task
from pokemon_agent.config import PLAN_MAX_NEW_GOALS
from pokemon_agent.schemas.harness import FromHarnessToBrainToolPlanOnceReq
from pokemon_agent.schemas.harness.domain import GoalEntry, GoalStatus
from pokemon_agent.tools.interface import BrainToolPort

from .interface.planner_context import PlannerContext
from .interface.planner_outcome import GoalUpdate, PlannerOutcome


class BrainPlanner:
    """模型侧的 `Planner`：组 `PlanOnceReq` → 调 `BrainTool.plan()` → 转成 `PlannerOutcome`。"""

    def __init__(self, brain_tool: BrainToolPort) -> None:
        """接上大脑那一侧的 tool（`BrainToolPort`）。

        依赖注入而不是自己 new：`BrainToolPort` 由装配点（`build.py`）给，
        测试里换成假实现即可——与 `HarnessDeps` 里其余四根 Port 同一个口径。
        """
        self._brain_tool = brain_tool

    def plan(self, ctx: PlannerContext) -> PlannerOutcome:
        """读记忆与目标表 → 问模型 → 转成 run 级编排形状。

        前置条件：`ctx.plan` 是当前目标表（可以为空表——首次规划时就是）。
        后置条件：`entries` 全部是 `PENDING` 的新条目、`task_id` 在表内唯一；
            `updates` 只含 `PENDING`（重开）/ `ABANDONED`（放弃）两个状态。
        失败：`BrainTool.plan()` 的 `MaxRetriesExceeded` **原样上抛**——
            `Planner` 的失败契约就是"抛异常"（空产出是"我没意见"这个正常结论，
            两者必须分得开）。
        """
        req = FromHarnessToBrainToolPlanOnceReq(
            run_id=ctx.run_id,
            plan=ctx.plan,
            index=ctx.index,
            details=ctx.details,
            objects=ctx.objects,
            max_push=PLAN_MAX_NEW_GOALS,
        )
        result = self._brain_tool.plan(req)
        run_plan = result.plan

        entries = [
            GoalEntry(
                task=self._to_task(ctx, plan_goal, offset),
                status=GoalStatus.PENDING,
            )
            for offset, plan_goal in enumerate(run_plan.push_goals)
        ]
        # 模型按**表内序号**指名（prompt 里 `[0]`/`[1]` 那个），这里翻译成 `task_id`
        # ——序号是"位置"，task_id 是"身份"，越界（模型数错行）就丢这条表态：
        # 数错不是异常，只是这条作废。
        updates = [
            GoalUpdate(
                task_id=ctx.plan[update.index].task.task_id,
                status=GoalStatus(update.status),
                note=update.note,
            )
            for update in run_plan.updates
            if 0 <= update.index < len(ctx.plan)
        ]
        return PlannerOutcome(
            entries=entries,
            updates=updates,
            done=run_plan.done,
            why=run_plan.why,
            input=result.calls[-1].payload.get("prompt", ""),
            output=result.calls[-1].payload.get("raw", ""),
        )

    # ---- 内部 ----

    def _to_task(self, ctx: PlannerContext, plan_goal: RunPlan.PlanGoal, offset: int) -> Task:
        """`RunPlan.PlanGoal` → `Task`（brain 的领域模型），`task_id` 由这里生成。

        **为什么带 `offset`**：一次规划可能给出多条新目标，`_next_task_id` 只看
        已有表，会给出同一个号——所以按条数递增。
        """
        return Task(
            task_id=_next_task_id(ctx.plan, ctx.run_id, offset),
            goal=plan_goal.goal,
            success_criteria=plan_goal.success_criteria,
            max_steps=plan_goal.max_steps,
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


__all__ = ["BrainPlanner"]
