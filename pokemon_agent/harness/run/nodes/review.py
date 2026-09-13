"""`review`：human-in-the-loop——目标被弹出后或 plan 连续失败后，把结果交给人类。

**它是本图唯一"人可以在环里"的格子**：调 `HumanReviewer`（注入的实现可能是
`AutoContinueReviewer`、前端的 `DataCenterReviewer`、或测试假件），按决策回
`continue`（回 `plan`）/ `stop`（结束 run）/ `retry`（刚弹出的目标压回栈顶）。

加/改/删目标统一走 `POST /runs/{id}/goals`（整栈原子替换），**不是这里的第四个
决策分支**——`PUSH` 已删（决定记录见 `CHANGELOG.md` 2026-09-04 条目）。

`episode_trace_events` 住本文件：它唯一的调用点就是本节点（"把刚跑完那一局的
完整 trace 塞进 review 请求"，D8-②）。
"""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from pokemon_agent.schemas.harness import FromHarnessToReviewerReviewReq
from pokemon_agent.trace import TraceEvent

from ...deps import HarnessDeps
from ...interface import HumanDecision
from ..run_state import RunState


def episode_trace_events(events: list[TraceEvent], episode_id: str) -> list[TraceEvent]:
    """从全量事件流里挑出单个 episode 的完整 trace（`events` 已按 event_id
    升序，见 `TracePort.events`，这里原序保留）。

    `TracePort.events` 只支持按 `EventType` mask，不支持按 `episode_id`
    过滤——`review()` 节点要把"刚跑完那一局的完整 trace"塞进
    `FromHarnessToReviewerReviewReq.episode_trace`，这里在 Python 侧按
    `episode_id` 筛一遍（调用方传 `events(None)` 的全量结果进来）。
    """
    return [ev for ev in events if ev.episode_id == episode_id]


def review(state: RunState, runtime: Runtime[HarnessDeps]) -> dict[str, Any]:
    """**human-in-the-loop**：目标被弹出后（成功或重试耗尽）或 plan 连续失败后，
    把结果交给人类。

    调 `HumanReviewer`，按决策路由：
    - `CONTINUE` → 回 plan（plan 连续失败时，这里是一次人工放行）
    - `STOP`     → 置 done，结束 run（→ END）
    - `RETRY`    → 刚弹出的目标压回栈顶（幂等：失败保留栈顶的情形它没被
                   弹出，重试 = 直连重派，这里无需动作）

    `PUSH` 决策已删——加/改/删目标统一走
    `POST /runs/{id}/goals`（`FromFrontendToRunHarnessSubmitEditReq`，整栈原子替换），跟"这一轮
    episode 怎么办"分开，用户确认"只保留 goal 的 push（整栈同步）和
    goals 的 read（独立的 `GET /runs/{id}/goals`），去掉 review 的 push"。

    依赖从 `runtime.context` 取（`data_center` 两槽 + `reviewer`）：本节点是
    "人和图之间的那扇门"，两件都必须是**装配时注入的同一个实例**——自己新建一份
    的表现是"前端看不到请求、图却照跑"。
    """
    deps = runtime.context
    data_center = deps.data_center
    assert data_center is not None, "review() needs a data_center (装配时注入)"
    episode_trace = (
        episode_trace_events(data_center.events(), state.episode_id) if state.episode_id else []
    )
    req = FromHarnessToReviewerReviewReq(
        run_id=state.run_id,
        outcomes=state.outcomes,
        goals=state.goals,
        last_task=state.task,
        episode_trace=episode_trace,
    )
    data_center.publish_review_request(req)
    resp = deps.reviewer.review(req)
    data_center.clear_review()

    if resp.decision is HumanDecision.CONTINUE:
        return {}
    if resp.decision is HumanDecision.STOP:
        return {"done": True, "why": "human stopped"}
    if resp.decision is HumanDecision.RETRY:
        assert state.task is not None, "RETRY without a last task"
        if state.goals and state.goals[-1] == state.task:
            return {}
        return {
            "goals": state.goals + [state.task],
            "attempts": state.attempts + [0],
        }
    raise AssertionError(f"unknown human decision: {resp.decision!r}")


__all__ = ["episode_trace_events", "review"]
