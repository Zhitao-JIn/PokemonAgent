"""问人时的**渲染口径**：把表单、被审结论、被审对象的事件变成给人读的文本。

`ConsoleReviewer` 与 `WebReviewer` 共用这一份——同一张表单在终端和网页上说同样的话。
只依赖 schemas；不懂任何实现的传输方式。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToReviewerAuditReq,
    TraceEvent,
)
from pokemon_agent.schemas.harness.domain import EpisodeOutput, TaskOutput

EVENT_CONTENT_LIMIT = 160
"""事件行里 content 的截断长度（字）。"""


def format_form(form: Any) -> str:  # noqa: ANN401 —— 信封的 form 本来就是任意结构体
    """把一张表单渲染成文本：pydantic 模型走 `model_dump_json(indent=2)`，其余 `str()`。"""
    dump = getattr(form, "model_dump_json", None)
    if callable(dump):
        return dump(indent=2)
    return str(form)


def outcome_kind(outcome: EpisodeOutput | TaskOutput | FromHarnessToBrainToolJudgeResp) -> str:
    """被审对象的种类标签：`EpisodeOutput` / `TaskOutput` / `JudgeVerdict`。"""
    if isinstance(outcome, FromHarnessToBrainToolJudgeResp):
        return "JudgeVerdict"
    return type(outcome).__name__


def audit_prompt(req: FromHarnessToReviewerAuditReq) -> str:
    """一句话说明这次审的是什么。"""
    outcome = req.outcome
    if isinstance(outcome, FromHarnessToBrainToolJudgeResp):
        return "审模型裁决：本层目标真的已经达成、可以收工了吗？"
    if isinstance(outcome, TaskOutput):
        return f"审 task 结果：{req.task_id} 算成算败？"
    return f"审一局的结果：{req.episode_id} 算成算败？"


def render_outcome(req: FromHarnessToReviewerAuditReq) -> str:
    """被审结论的文本：机械结算四行，或模型裁决两行。"""
    outcome = req.outcome
    if isinstance(outcome, FromHarnessToBrainToolJudgeResp):
        return f"  模型说   {'已达成' if outcome.done else '未达成'}\n  理由     {outcome.why}\n"
    verdict_line = "成功" if outcome.success else "失败"
    if isinstance(outcome, TaskOutput):
        who = f"  task   {req.task_id}（局 {req.episode_id}）\n"
        counts = f"{outcome.steps_used} 键"
    else:
        who = f"  局号   {req.episode_id}\n"
        counts = f"{outcome.tasks_used} 个 task / {outcome.acts_used} 键"
    return (
        f"{who}"
        f"  裁定   {verdict_line}（{outcome.termination.value}，{counts}）\n"
        f"  依据   {outcome.judge_reason or '（无）'}\n"
        f"  结论   {outcome.reason or '（无）'}\n"
    )


def render_events(events: list[TraceEvent]) -> list[str]:
    """每条事件一行：`时刻 · kind · source · step · content 截断`；meta 解不动的跳过。"""
    lines: list[str] = []
    for event in events:
        try:
            meta = json.loads(event.meta)
        except json.JSONDecodeError:
            continue
        clock = datetime.fromtimestamp(event.ts).strftime("%H:%M:%S")
        content = " ".join(event.content.split())
        if len(content) > EVENT_CONTENT_LIMIT:
            content = content[:EVENT_CONTENT_LIMIT] + "…"
        where = f"{meta.get('source', '-')} · {meta.get('step', '-')}"
        lines.append(f"{clock} · {event.kind} · {where} · {content}")
    return lines


__all__ = [
    "EVENT_CONTENT_LIMIT",
    "audit_prompt",
    "format_form",
    "outcome_kind",
    "render_events",
    "render_outcome",
]
