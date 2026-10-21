"""地形图例的排版。"""

from pathlib import Path
from string import Template

from ....interfaces.assembly import Compose
from .params import TerrainLegendParams


def assemble(params: TerrainLegendParams, compose: Compose) -> str:
    """依符号表原顺序排版，不维护第二份含义。"""
    template = Template(Path(__file__).with_name("prompt.md").read_text(encoding="utf-8"))
    return "\n".join(
        template.substitute(symbol=symbol, meaning=meaning)
        for symbol, meaning in params.meanings.items()
    )
