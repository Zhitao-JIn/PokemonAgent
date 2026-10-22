"""注册片段 v1：固定文本与原料排版。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from ....interfaces.assembly import Compose
from ....records import GoalRecord
from .params import GoalTableParams

_LABELS = json.loads(
    Path(__file__)
    .with_name("prompt.md")
    .read_text(encoding="utf-8")
    .split("<!-- labels -->\n", 1)[1]
)


def goals_lines(plan: Sequence[GoalRecord]) -> list[str]:
    """按原条件和顺序渲染独立原料。"""
    lines: list[str] = []
    for i, entry in enumerate(plan):
        overturned = _LABELS["L000"] if entry.overturned else ""
        tried = _LABELS["L001"].format(entry.attempts) if entry.attempts else ""
        note = _LABELS["L002"].format(entry.note) if entry.note else ""
        lines.append(
            _LABELS["L004"].format(
                i,
                format(entry.status, "<9"),
                overturned,
                entry.task.goal,
                entry.task.success_criteria,
                entry.task.max_steps,
                entry.task.task_id,
                entry.last_episode_id or _LABELS["L003"],
                tried,
                note,
            )
        )
    return lines


def assemble(params: GoalTableParams, compose: Compose) -> str:
    """输出素材行，内部逐条出口保留原列表边界。"""
    lines = goals_lines(params.entries)
    return json.dumps(lines, ensure_ascii=False) if params.serialized else "\n".join(lines)
