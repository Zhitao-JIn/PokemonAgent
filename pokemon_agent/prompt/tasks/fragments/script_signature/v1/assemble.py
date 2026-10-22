"""脚本签名排版 v1。"""

import json
from pathlib import Path

from ....interfaces.assembly import Compose
from .params import ScriptSignatureParams

_LABELS = json.loads(Path(__file__).with_name("prompt.md").read_text(encoding="utf-8"))


def assemble(params: ScriptSignatureParams, compose: Compose) -> str:
    """无参只给名字；默认值保留 Python repr 的旧语义。"""
    entry = params.entry
    if not entry.params:
        return entry.name
    parts = [
        _LABELS["parameter"].format(p.name, p.type)
        + ("" if p.default is None else _LABELS["default"].format(repr(p.default)))
        for p in entry.params
    ]
    return _LABELS["call"].format(entry.name, _LABELS["separator"].join(parts))
