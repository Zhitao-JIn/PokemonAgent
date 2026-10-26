"""同一份目标正文用于三个 plan 节点。"""

import json
from pathlib import Path

from ....interfaces.assembly import Compose
from .params import GoalParams

_LABELS = json.loads(Path(__file__).with_name("prompt.md").read_text(encoding="utf-8"))


def assemble(params: GoalParams, compose: Compose) -> str:
    """前置：目标非空、当前索引有效；后置：保留原文，有判据才显示判据。"""
    assert params.entries, "Goal requires entries"
    assert params.current_index is None or 0 <= params.current_index < len(params.entries)
    lines: list[str] = []
    for index, entry in enumerate(params.entries):
        marker = _LABELS["current"] if index == params.current_index else ""
        lines.append(_LABELS["goal"].format(entry.goal, marker))
        if entry.criteria:
            lines.append(_LABELS["criteria"].format(entry.criteria))
    return "\n".join(lines)
