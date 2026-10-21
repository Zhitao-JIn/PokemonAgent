"""注册片段 v1：固定文本与原料排版。"""

from __future__ import annotations

import json
from pathlib import Path

from ....interfaces.assembly import Compose
from ....records import JudgeFeedbackRecord
from .params import LastJudgeParams

_LABELS = json.loads(
    Path(__file__)
    .with_name("prompt.md")
    .read_text(encoding="utf-8")
    .split("<!-- labels -->\n", 1)[1]
)


def last_judge_lines(feedback: JudgeFeedbackRecord) -> list[str]:
    """按原条件和顺序渲染独立原料。"""
    said = feedback.decision
    lines = [_LABELS["L000"].format(said, feedback.why)]
    if feedback.audit == "overturn":
        lines.append(_LABELS["L002"].format(feedback.note or _LABELS["L001"]))
    return lines


def assemble(params: LastJudgeParams, compose: Compose) -> str:
    """输出素材行，内部逐条出口保留原列表边界。"""
    lines = last_judge_lines(params.feedback)
    return json.dumps(lines, ensure_ascii=False) if params.serialized else "\n".join(lines)
