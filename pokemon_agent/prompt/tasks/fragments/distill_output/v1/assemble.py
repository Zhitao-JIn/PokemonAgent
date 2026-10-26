"""三层共用蒸馏输出说明，固定字段说明先于分层建议。"""

import json
from pathlib import Path
from string import Template

from ....interfaces.assembly import Compose
from .params import DistillOutputParams

_TEXT, _WORDS = (
    Path(__file__)
    .with_name("prompt.md")
    .read_text(encoding="utf-8")
    .split("\n<!-- labels -->\n", 1)
)
_LABELS = json.loads(_WORDS)


def assemble(params: DistillOutputParams, compose: Compose) -> str:
    """前置：层名有效；后置：输出字段完整，分层建议不改变字段契约。"""
    return Template(_TEXT).substitute(compact_note=_LABELS[params.scope])
