"""人类插话片段 v1。"""

from pathlib import Path
from string import Template

from ....interfaces.assembly import Compose
from .params import HumanNoteParams


def assemble(params: HumanNoteParams, compose: Compose) -> str:
    """调用方保证原话去掉首尾空白后非空。"""
    assert params.note.strip()
    return Template(Path(__file__).with_name("prompt.md").read_text(encoding="utf-8")).substitute(
        note=params.note.strip()
    )
