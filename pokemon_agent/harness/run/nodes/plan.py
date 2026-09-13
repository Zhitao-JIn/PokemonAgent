"""`plan`：**LLM 决策器**——读 trace 历史 + 目标栈 → 问规划模型 → 应用决策（run 图的入口下一格）。

决策三条路：

- 压栈（`push_goals`，截断到 `MAX_PLAN_PUSH`）→ 追加 goals/attempts，继续；
- `done`（或栈空且不压）→ 置 done，run 结束；
- 连续 `BRAIN_MAX_ATTEMPTS` 次调用/解析失败 → 置 `plan_failed`，路由 review。

**账写在它的宿主里**：每次调用的账（`MODEL_CALL`，`Source.PLAN`）由本节点写。
**重试循环在 `BrainTool.plan()` 那一层**（跟 `choose` 同一手法）
——本节点退化成"组装 → 交一次 → 落账"；成功走 `resp.calls`，耗尽走异常携带的
`exc.calls`。**不用 `Source.HARNESS`**：那是
零成本记账事件的桶，`plan` 是一次真实模型调用，跟 episode 内的 `DECISION` 平级，
该有自己的链路。三条非 `plan_failed` 的出口都额外补一条 `PLAN_VERDICT` 账（tool 按
kind 渲染）——账单只答"花了多少钱"，这条答"这一格给了什么结论"，复盘"planner 这次
为什么压了这个目标"靠它。

三个同族件住本文件（D8-②：跟着唯一的调用者走）：

- `to_tasks` / `apply_goals_edit`——都只服务本节点：前者把模型压的目标转成
  `Task`，后者把观测台的编辑指令应用到目标栈（与 `plan` 同族：都是"改目标栈"）；
- `RUN_TRACE_MASK`——本节点读 trace 的历史口径。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.brain import RunPlan, Task
from pokemon_agent.config import MAX_PLAN_PUSH
from pokemon_agent.errors import MaxRetriesExceeded
from pokemon_agent.schemas.frontend import FromFrontendToRunHarnessSubmitEditReq
from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolPlanOnceReq,
    FromHarnessToTraceToolAppendModelCallsReq,
    FromHarnessToTraceToolAppendReq,
    ModelCallLog,
    TraceKind,
)
from pokemon_agent.tools.interface import BrainToolPort
from pokemon_agent.trace import EventType, Source

from ...deps import HarnessDeps
from ..run_state import RunState

RUN_TRACE_MASK = frozenset({EventType.LIFECYCLE, EventType.ERROR})
"""run 级 plan 读 trace 时的 type 粗 mask——只取流程边界 + 失败两种家族，
单步噪声（VIEW/ACT/MEMORY_IO/LLM_OUTCOME/MODEL_CALL）整族滤掉；LIFECYCLE
里 run/episode 边界与 step 刻度混在同一 type，靠 `prompts.run_plan` 里的
折算逻辑按 payload kind 再筛一层（type 只到家族粒度，语义在 kind）。"""


def to_tasks(goals: list[RunPlan.PlanGoal], run_id: str) -> list[Task]:
    """把 LLM 的新目标转成可派发的任务——`task_id` 由 harness 生成
    （`plan-{run_id}-{序号}`），run 级自主拆解的目标没有实验分组键。"""
    return [
        Task(
            task_id=f"plan-{run_id}-{i + 1}",
            goal=g.goal,
            success_criteria=g.success_criteria,
            max_steps=g.max_steps,
        )
        for i, g in enumerate(goals)
    ]


def apply_goals_edit(state: RunState, edit: FromFrontendToRunHarnessSubmitEditReq) -> None:
    """把观测台的编辑指令应用到当前目标栈（原地改 `state`）：整栈原子替换、
    不锁栈顶——前端把目标栈变成纯本地草稿（含栈顶），只在 review 阶段可
    编辑，点 push 时一次性把整份草稿同步过来。

    `attempts` 按 `task_id` 找回旧计数，新目标（`task_id` 没出现过）记 0。

    `strict=False`：这是**原样搬来**的那一行（此前住 `run_utils.py`），保持行为不变
    ——两边长度为 0 的短表在 `.get(..., 0)` 那里等价于"新目标记 0"，不在这里改语义。
    """
    old_attempts = dict(zip((g.task_id for g in state.goals), state.attempts, strict=False))
    state.goals = list(edit.goals)
    state.attempts = [old_attempts.get(g.task_id, 0) for g in edit.goals]


def ask_planner_with_retry(
    brain_tool: BrainToolPort,
    req: FromHarnessToBrainToolPlanOnceReq,
) -> tuple[RunPlan | None, ModelCallLog]:
    """问一次规划（重试在 `BrainTool.plan()` 里），把整条账交回来。

    调用方只传素材；prompt 由 `BrainTool.plan()` 入口拼。**重试原样重问**——
    不像 `decide_action` 那样叠加纠正说明（`run_plan` 的重试策略跟
    `decide_action` 不是一回事），所以循环里每次尝试都传同一个 `req`。

    账（`Source.PLAN`；run 级事件不挂在任何一局上，所以调用方写账时
    `episode_id` 位放 run_id、`step` 用 0）：成功走 `resp.calls`，
    耗尽走异常携带的 `exc.calls`——两条路都返回 `(None 或 plan, log)`，
    调用方不用 catch。

    `BrainToolPort` 是**参数**而不是从 `runtime` 里取（本函数不依赖 `runtime`）：
    这样能用假端口独立测，不依赖装配。
    """
    try:
        resp = brain_tool.plan(req)
    except MaxRetriesExceeded as exc:
        return None, [(i, call) for i, call in enumerate(exc.calls, start=1)]

    return resp.plan, [(i, call) for i, call in enumerate(resp.calls, start=1)]


def plan(state: RunState, runtime: Runtime[HarnessDeps]) -> dict[str, Any]:
    """**LLM 决策器**：读历史 + 目标栈 → 问规划模型 → 应用决策。

    重试循环、解析、编辑应用都在本文件，**prompt 拼装在 `BrainTool.plan()`**
    ——这里只决定"问完之后走哪条路"。

    **入栈顺序：`state.goals + pushes` 原序 append，栈顶 = `goals[-1]`**
    ——这是纯 LIFO：`push_goals` 列表里**最后**一项会变成新栈顶、最先被
    派发。不是"列表第一项优先级最高、最先执行"，而是"后压的先做"——
    列表本身就该按"先出现的先入栈（压得更深），后出现的后入栈（压在
    最上面、最先执行）"这个顺序给，模型自己要清楚这一点，harness 不该
    替它倒转顺序（顺序曾被反转过一次又纠正，事故记录见 `CHANGELOG.md`
    2026-09-04 条目）。这里只负责按 LIFO 老实 append。`review()` 的
    `PUSH` 分支是同一个约定；`apply_goals_edit`（`POST /runs/{id}/goals`）
    是整栈同步，不走按 `push` 分支单独 append。

    两个行为开关从 `deps` 读（构造时定，整 run 不变）：`auto_push_goals` 决定
    模型能不能自主压栈，`auto_decide_done` 决定它能不能判整个 run 结束。
    """
    deps = runtime.context
    data_center = deps.data_center
    assert data_center is not None, "plan() needs a data_center (装配时注入)"

    # 先消费观测台的编辑指令（单槽，最新一条），再问 LLM——编辑后的
    # 目标栈要进本次决策的 prompt。栈顶锁定在 `apply_goals_edit` 内校验。
    # 快照**不在入口记录**：LLM 压栈发生在出口（state 合并前），
    # 入口快照会漏掉本轮的 push_goals——观测台将看不到 plan 自主拆的目标。
    # 这一步无论下面跳不跳模型调用都要做——人工编辑通道
    # （`POST /runs/{id}/goals`）不受这两个开关影响。
    edit = data_center.take_goals_edit()
    if edit is not None:
        apply_goals_edit(state, edit)

    # 两个开关都关掉时**真的跳过这次调用**：`resp.push_goals` 会被强制
    # 清空、`resp.done` 不会被采信——不管模型这次说了什么，落到 state 里的
    # 效果都跟"没问"完全一样（对照下面走完整条链路时最后的兜底分支：
    # `pushed=[]`、`done=False`）。既然结果注定被扔，这次真实调用（一整笔
    # token）就是纯浪费，直接跳过，图路由不变（走跟"问完但没压栈/没判 done"
    # 完全一样的返回形状，`run_graph.py` 的条件边照旧看
    # `plan_failed`/`done`/`goals` 判走 dispatch 还是 review）。
    if not deps.auto_push_goals and not deps.auto_decide_done:
        data_center.publish_goals(state.goals)
        why = "auto_push_goals / auto_decide_done 均关闭，plan 跳过模型调用"
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.PLAN_VERDICT,
                step=0,
                episode_id=state.run_id,
                done=False,
                pushed=[],
                why=why,
            )
        )
        return {"plan_failed": False}

    events = data_center.events(RUN_TRACE_MASK)
    req = FromHarnessToBrainToolPlanOnceReq(
        run_id=state.run_id,
        goals=state.goals,
        events=events,
        max_push=MAX_PLAN_PUSH,
    )
    # prompt **不在这里拼**（0913 定案）：本节点只装素材，`BrainTool.plan()`
    # 入口拼（`prompts.run_plan.build_prompt()`）。

    resp, log = ask_planner_with_retry(deps.brain_tool, req)
    # 步骤：把这次规划的每一次尝试落成账（失败的那几次也要——它们同样烧了
    # token）。run 级事件不挂在任何一局上，`episode_id` 位放 run_id、step 用 0。
    deps.trace.append_model_calls(
        FromHarnessToTraceToolAppendModelCallsReq(
            episode_id=state.run_id, step=0, source=Source.PLAN, log=log
        )
    )
    if resp is None:
        # 预算耗尽：账（上面那条 append_model_calls）之外，再补一条只说明
        # "这个节点完了、为什么"的 `PLAN_FAILED`（0913 定案：失败事件不带账）。
        # `last_reason` 从最后一条账的错误里取——`ask_planner_with_retry` 把
        # 异常吞成 `None` 了，异常上的 `last_reason` 没带出来，这里就地取。
        last = log[-1][1] if log else None
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.PLAN_FAILED,
                episode_id=state.run_id,
                step=0,
                why=f"{last.error_kind}: {last.error}" if last else "no attempts recorded",
            )
        )
        data_center.publish_goals(state.goals)
        # `plan_note` 不再记（0913 定案）：人工审查**直接看 trace**
        # ——耗尽现场的那条 `PLAN_FAILED`（含 reason）与整条失败账
        # （`MODEL_CALL`，含每次的请求 payload）都在事件流里，比一份
        # 复制到 state 的 prompt 副本更完整，也少一处要同步维护的状态。
        return {"plan_failed": True}

    # `auto_push_goals=False` 时强制清空——模型的 `push_goals` 照常问、
    # 照常解析（省事，`run_plan.md` 不用跟着改），只是这里不采纳。
    pushes = to_tasks(resp.push_goals[:MAX_PLAN_PUSH], state.run_id) if deps.auto_push_goals else []
    # `auto_decide_done=False` 时同理：`resp.done` 不算数，栈空也不算数——
    # 两种情形都不在这里判 `done`，直接落到最后的"什么都不做"分支，
    # 交给 `run_graph.py` 的路由（`not s.goals` → `review`）去问人。
    # `auto_decide_done=True`（缺省）时：这两种情形都直接判 `done`，不经 `review()`。
    if deps.auto_decide_done and (resp.done or (not state.goals and not pushes)):
        data_center.publish_goals(state.goals)
        why = resp.why or (
            "全部目标解决" if all(o.success for o in state.outcomes) else "存在重试耗尽的目标"
        )
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.PLAN_VERDICT,
                step=0,
                episode_id=state.run_id,
                done=True,
                pushed=[],
                why=why,
            )
        )
        return {"plan_failed": False, "done": True, "why": why}
    if pushes:
        new_goals = state.goals + pushes
        data_center.publish_goals(new_goals)
        deps.trace.append(
            FromHarnessToTraceToolAppendReq(
                kind=TraceKind.PLAN_VERDICT,
                step=0,
                episode_id=state.run_id,
                done=False,
                pushed=[p.goal for p in pushes],
                why=resp.why,
            )
        )
        return {
            "plan_failed": False,
            "goals": new_goals,
            "attempts": state.attempts + [0] * len(pushes),
        }
    data_center.publish_goals(state.goals)
    deps.trace.append(
        FromHarnessToTraceToolAppendReq(
            kind=TraceKind.PLAN_VERDICT,
            step=0,
            episode_id=state.run_id,
            done=False,
            pushed=[],
            why=resp.why,
        )
    )
    return {"plan_failed": False}


__all__ = [
    "RUN_TRACE_MASK",
    "apply_goals_edit",
    "ask_planner_with_retry",
    "plan",
    "to_tasks",
]
