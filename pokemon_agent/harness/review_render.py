"""问人时的**渲染口径**：把表单、被审结论、被审对象的事件变成给人读的文本。

`ConsoleReviewer` 与 `WebReviewer` 共用这一份——同一张表单在终端和网页上说同样的话。
只依赖 schemas；不懂任何实现的传输方式。
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel

from pokemon_agent.schemas.harness import (
    FromHarnessToBrainToolJudgeResp,
    FromHarnessToReviewerAuditReq,
    TraceEvent,
)

EVENT_CONTENT_LIMIT = 160
"""事件行里 content 的截断长度（字）。"""


def format_form(form: Any) -> str:  # noqa: ANN401 —— 信封的 form 本来就是任意结构体
    """把一张表单渲染成**给人读**的文本。

    pydantic 模型：一行一个字段（`字段名: 值`），嵌套模型与模型列表缩进递归，
    字符串值里的换行**原样保留**（续行对齐到值那一列）。其余对象退回 `str()`。

    **不用 JSON**——`model_dump_json` 是机器格式：字符串值里的每个真实换行都被
    转义成字面 `\\n` 两个字符，再连同引号花括号混进正文，人没法读
    （0925：网页与终端上"正文和换行符等符号混在一起"的病灶）。

    **空字段不渲染**（`None` / 空串 / 空列表）：表单是"LLM 填了什么"的陈列，
    没填的可选字段（`note=""` 之类）不打出来——这是降噪的取舍，与观测渲染
    "没读过必须明写"那条红线不冲突：那是"事实快照"，这是"待审的提案"。
    """
    if isinstance(form, BaseModel):
        return _render_model(form, "")
    return str(form)


def _render_model(model: BaseModel, indent: str) -> str:
    """一个模型渲成 `字段: 值` 行块；模型字段与模型列表各自缩进递归。"""
    lines: list[str] = []
    for name in type(model).model_fields:
        value = getattr(model, name)
        if _is_blank(value):
            continue
        if isinstance(value, BaseModel):
            lines.append(f"{indent}{name}:")
            lines.append(_render_model(value, indent + "  "))
        elif isinstance(value, list) and all(isinstance(v, BaseModel) for v in value):
            lines.append(f"{indent}{name}:")
            for i, item in enumerate(value, 1):
                lines.append(f"{indent}  [{i}]")
                lines.append(_render_model(item, indent + "    "))
        else:
            text = _render_leaf(value)
            first, *rest = text.splitlines() or [""]
            lines.append(f"{indent}{name}: {first}")
            gutter = " " * (len(indent) + len(name) + 2)
            lines.extend(gutter + line for line in rest)
    return "\n".join(lines)


def _is_blank(value: Any) -> bool:  # noqa: ANN401
    return value is None or (isinstance(value, (str, list)) and not value)


def _render_leaf(value: Any) -> str:  # noqa: ANN401
    """叶子值转文本：枚举取 `.value`（别渲染成 `AuditVerdict.ACCEPT`），
    标量列表用 ` / ` 连接，其余 `str()`。"""
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, list):
        return " / ".join(str(v.value) if isinstance(v, Enum) else str(v) for v in value)
    return str(value)


def outcome_kind(outcome: FromHarnessToBrainToolJudgeResp) -> str:
    """被审对象的种类标签：`JudgeVerdict`。"""
    return "JudgeVerdict"


def audit_prompt(req: FromHarnessToReviewerAuditReq) -> str:
    """一句话说明本次审的是 judge 的目标达成裁决。"""
    return "审模型裁决：本层目标真的已经达成、可以收工了吗？"


def render_outcome(req: FromHarnessToReviewerAuditReq) -> str:
    """把模型裁决与理由渲染为两行文本。"""
    outcome = req.outcome
    return f"  模型说   {'已达成' if outcome.done else '未达成'}\n  理由     {outcome.why}\n"


def render_events(events: list[TraceEvent]) -> list[str]:
    """每条事件一行：`时刻 · kind · source · step · content 截断`；meta 解不动的跳过。"""
    lines: list[str] = []
    for event in events:
        try:
            meta = json.loads(event.meta)
        except json.JSONDecodeError:
            continue
        clock = datetime.fromtimestamp(event.ended_at).strftime("%H:%M:%S")
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
