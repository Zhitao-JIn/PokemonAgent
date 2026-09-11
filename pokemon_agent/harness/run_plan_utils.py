"""`RunHarness`（run 级图）与大脑交互专用的工具函数。

**只放这一根依赖会用到的重试循环、记账与纯计算**——跟 `run_utils.py`
（图控制本身用到的、不绑定任何依赖的纯函数）是同一层拆分：那边放
`goal_retries_exhausted`/`apply_goals_edit` 这类只碰 `RunState`/`FromFrontendToRunHarnessSubmitEditReq`
的函数，这里放"问规划模型"这一整条链路会用到的东西。

`ask_planner_with_retry` 是依赖注入的编排函数：`BrainToolPort`/`TraceToolPort`
是**参数**、不是 `self` 属性——调用方（`RunHarness.plan()`）传自己的
`self._brain`/`self._trace` 进来，这里就能用假端口独立测试。

run 级规划的原始文本 → `RunPlan` 解析（剥 json 围栏、`json.loads`、
字段校验）在 `brain/brain.py::Brain._parse_plan` 里，跟
`choose_once`/`Brain._parse` 同一个位置——`plan` 是"另一种要问模型的问题"，
不是"另一个模块的原始返回值"。这里只剩"问、重试、记账"和"契约内对象
之间怎么互相编排"。
"""

from __future__ import annotations

from pokemon_agent.brain import RunPlan, TaskForBrain
from pokemon_agent.errors import PlanAttemptFailed
from pokemon_agent.interfaces import PLAN_MAX_ATTEMPTS
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolPlanOnceReq,
    FromHarnessToTraceToolAppendReq,
)
from pokemon_agent.schemas.trace import EventType, Source
from pokemon_agent.tools import BrainToolPort, TraceToolPort
from pokemon_agent.trace import TraceKind

RUN_TRACE_MASK = frozenset({EventType.LIFECYCLE, EventType.ERROR})
"""run 级 plan 读 trace 时的 type 粗 mask——只取流程边界 + 失败两种家族，
单步噪声（VIEW/ACT/MEMORY_IO/LLM_OUTCOME/MODEL_CALL）整族滤掉；LIFECYCLE
里 run/episode 边界与 step 刻度混在同一 type，靠 `prompts.run_plan` 里的
折算逻辑按 payload kind 再筛一层（type 只到家族粒度，语义在 kind）。"""


def to_tasks(goals: list[RunPlan.PlanGoal], run_id: str) -> list[TaskForBrain]:
    """把 LLM 的新目标转成可派发的任务——`task_id` 由 harness 生成
    （`plan-{run_id}-{序号}`），run 级自主拆解的目标没有实验分组键。"""
    return [
        TaskForBrain(
            task_id=f"plan-{run_id}-{i + 1}",
            goal=g.goal,
            success_criteria=g.success_criteria,
            max_steps=g.max_steps,
        )
        for i, g in enumerate(goals)
    ]


def ask_planner_with_retry(
    brain_tool: BrainToolPort,
    trace: TraceToolPort,
    run_id: str,
    req: FromHarnessToBrainToolPlanOnceReq,
) -> tuple[RunPlan | None, bool]:
    """反复问一次规划，最多 `PLAN_MAX_ATTEMPTS` 次——**循环、端口调用、记账都
    在这里**，`brain_tool.plan_once()` 只负责单次尝试（问模型 + 解析），跟
    `brain_utils.choose_with_retry` 是同一个模式在 run 级图上的落地。

    `req.prompt` 是调用方已经拼好回填过的完整 prompt；**重试原样重问**——
    不像 `choose_with_retry` 那样叠加纠正说明（`run_plan` 的重试策略跟
    `decide_action` 不是一回事），所以每次尝试都传同一个 `req`，不改写它。

    每次调用（成功失败都算）写一条 `MODEL_CALL` 账（`Source.PLAN`，
    episode_id 用 run_id、step 用 0——run 级事件不挂在任何一局上）。
    失败：全部尝试耗尽返回 `(None, False)`；成功返回 `(resp.plan, True)`。
    """
    for attempt in range(1, PLAN_MAX_ATTEMPTS + 1):
        # 步骤 1：问一次，记账；失败就进入下一次尝试。
        try:
            resp = brain_tool.plan_once(req)
        except PlanAttemptFailed as exc:
            trace.append(
                FromHarnessToTraceToolAppendReq(
                    kind=TraceKind.MODEL_CALL,
                    episode_id=run_id,
                    step=0,
                    source=Source.PLAN,
                    call=exc.call,
                    attempt=attempt,
                )
            )
            continue

        # 步骤 2：成功，记账，交回解析好的计划。
        trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.MODEL_CALL,
                episode_id=run_id,
                step=0,
                source=Source.PLAN,
                call=resp.calls[0],
                attempt=attempt,
            )
        )
        return resp.plan, True

    # 步骤 3：预算耗尽，交给调用方决定怎么收场（`RunHarness.plan()` 路由去 review）。
    return None, False
