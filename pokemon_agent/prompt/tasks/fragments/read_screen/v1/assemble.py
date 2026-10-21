"""静态片段保留原 Markdown 字节对应的文本。"""

from pathlib import Path

from ....interfaces.assembly import Compose
from .params import ReadScreenParams


def assemble(params: ReadScreenParams, compose: Compose) -> str:
    """返回固定规则。"""
    return Path(__file__).with_name("prompt.md").read_text(encoding="utf-8")
