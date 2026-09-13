"""`run_plan.md` 的装配逻辑：加载、拼装、渲染，都在这一个文件里。

跟 `decide_action.py`/`judge_success.py`/`verify_and_summarize.py` 同一个
模式——`RunHarness` 只负责查 trace、组装 `PlanOnceReq`（`events`/`goals` 保持
结构化），struct→text（trace 事件折成「每局一行」历史、目标栈渲成带箭头的
多行文本）交给这里的 `build_prompt()`——五份 prompt 的组装方式保持一致。
"""

from __future__ import annotations

from pokemon_agent.schemas.harness import FromHarnessToBrainToolPlanOnceReq
from pokemon_agent.trace import EventType, TraceEvent

from . import load

_TEMPLATE = load("run_plan")


def history_lines(events: list[TraceEvent]) -> list[str]:
    """把 mask 过的事件流折成**每局一行**的历史摘要，返回**行列表**。

    **公开，且返回列表而不是拼好的串**：两个调用方共用这一份实现——
    `build_prompt()` 把行拼成整段塞进 prompt，`BrainTool.plan()` 把行原样
    交给 `Brain.plan(history=…)`（brain 的约定要求"发生过什么"独立成块）。
    **分两份实现迟早漂移**（一处改了措辞、另一处没改，事件里和 prompt 里
    的历史就不一样了），所以这里是唯一真源。
    """
    starts: dict[str, str] = {}
    ends: dict[str, str] = {}
    for ev in events:
        kind = ev.payload.get("kind", "")
        if ev.type == EventType.LIFECYCLE and kind == "episode_start":
            starts[ev.episode_id] = str(ev.payload.get("goal", ""))
        elif ev.type == EventType.LIFECYCLE and kind == "episode_end":
            ok = ev.payload.get("success") == "True"
            ends[ev.episode_id] = (
                f"{'成功' if ok else '失败'}"
                f"（{ev.payload.get('steps', '?')} 步，{ev.payload.get('reason', '')}）"
            )
    return [f"- {ep}: {starts.get(ep, '')} → {ends[ep]}" for ep in ends]


def goals_lines(goals: list) -> list[str]:
    """目标栈渲染成**每目标一行**（栈顶标箭头），返回行列表。同 `history_lines`
    的理由：`build_prompt` 与 `BrainTool.plan` 共用这一份。"""
    if not goals:
        return []
    return [f"{'→ ' if i == len(goals) - 1 else '  '}{t.goal}" for i, t in enumerate(goals)]


def build_prompt(req: FromHarnessToBrainToolPlanOnceReq) -> str:
    """拼出这一轮 `plan` 用的完整 prompt。"""
    history = history_lines(req.events)
    goals = goals_lines(req.goals)
    return _TEMPLATE.render(
        history="\n".join(history) if history else "（尚无完成的 episode）",
        goals="\n".join(goals) if goals else "（空）",
        max_push=req.max_push,
    )
