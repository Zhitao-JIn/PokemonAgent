"""三层共用附图核对规则，按层保留既有来源与裁剪说明。"""

import json
from pathlib import Path
from string import Template

from ....interfaces.assembly import Compose
from .params import ImageReadingParams

_TEXT, _WORDS = (
    Path(__file__)
    .with_name("prompt.md")
    .read_text(encoding="utf-8")
    .split("\n<!-- labels -->\n", 1)
)
_LABELS = json.loads(_WORDS)


def assemble(params: ImageReadingParams, compose: Compose) -> str:
    """输出读图规则与本层来源，不接收或修改图片。"""
    return Template(_TEXT).substitute(source=_LABELS[params.scope])
