"""`run_plan.md` 的装配逻辑：加载、拼装、渲染，都在这一个文件里。

跟 `decide_action.py`/`judge_success.py`/`verify_and_summarize.py` 同一个
模式——`RunHarness` 只负责查 trace、组装 `FromBrainToolToBrainPlanOnceReq`（`events`/`goals` 保持
结构化），struct→text（trace 事件折成「每局一行」历史、目标栈渲成带箭头的
多行文本）交给这里的 `build_prompt()`——五份 prompt 的组装方式保持一致。
"""

from __future__ import annotations

from pokemon_agent.schemas.communication import FromBrainToolToBrainPlanOnceReq
from pokemon_agent.schemas.datastore import EventType, TraceEvent

from . import load

_TEMPLATE = load("run_plan")


def _history_lines(events: list[TraceEvent]) -> str:
    """把 mask 过的事件流折成**每局一行**的历史摘要（plan prompt 的历史段）。"""
    starts: dict[str, str] = {}
    ends: dict[str, str] = {}
    for ev in events:
        kind = ev.payload.get("kind", "")
        if ev.type is EventType.LIFECYCLE and kind == "episode_start":
            starts[ev.episode_id] = str(ev.payload.get("goal", ""))
        elif ev.type is EventType.LIFECYCLE and kind == "episode_end":
            ok = ev.payload.get("success") == "True"
            ends[ev.episode_id] = (
                f"{'成功' if ok else '失败'}"
                f"（{ev.payload.get('steps', '?')} 步，{ev.payload.get('reason', '')}）"
            )
    lines = [f"- {ep}: {starts.get(ep, '')} → {ends[ep]}" for ep in ends]
    return "\n".join(lines) if lines else "（尚无完成的 episode）"


def _goals_lines(goals: list) -> str:
    """目标栈渲染成多行文本，栈顶标箭头（plan prompt 的目标段）。"""
    if not goals:
        return "（空）"
    return "\n".join(
        f"{'→ ' if i == len(goals) - 1 else '  '}{t.goal}" for i, t in enumerate(goals)
    )


def build_prompt(req: FromBrainToolToBrainPlanOnceReq) -> str:
    """拼出这一轮 `plan` 用的完整 prompt。"""
    return _TEMPLATE.render(
        history=_history_lines(req.events),
        goals=_goals_lines(req.goals),
        max_push=req.max_push,
    )
