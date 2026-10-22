"""注册片段 v1：固定文本与原料排版。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from ....interfaces.assembly import Compose
from ....records import TaskTableRecord
from .params import TaskTableParams

_LABELS = json.loads(
    Path(__file__)
    .with_name("prompt.md")
    .read_text(encoding="utf-8")
    .split("<!-- labels -->\n", 1)[1]
)


def task_table_lines(table: Sequence[TaskTableRecord]) -> list[str]:
    """按原条件和顺序渲染独立原料。"""
    lines: list[str] = []
    for index, entry in enumerate(table):
        overturned = _LABELS["L000"] if entry.overturned else ""
        note = _LABELS["L001"].format(entry.note) if entry.note else ""
        lines.append(
            _LABELS["L003"].format(
                index,
                entry.entry_id,
                entry.round,
                entry.status,
                overturned,
                entry.task.goal,
                entry.task.success_criteria,
                entry.task.max_steps,
                entry.attempts,
                entry.last_task_id or _LABELS["L002"],
                note,
            )
        )
    return lines


def assemble(params: TaskTableParams, compose: Compose) -> str:
    """输出素材行，内部逐条出口保留原列表边界。"""
    lines = task_table_lines(params.entries)
    return json.dumps(lines, ensure_ascii=False) if params.serialized else "\n".join(lines)
