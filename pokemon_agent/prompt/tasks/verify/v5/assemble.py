"""verify v5：JSON闭合与简明证据，动态原料保持不变。"""

import json
from pathlib import Path
from string import Template

from ...interfaces.assembly import Compose
from ..fragments.memory_records.params import MemoryParams
from .params import VerifyParams


def assemble(params: VerifyParams, compose: Compose) -> str:
    """通过注册片段渲染素材，替换模板占位符。"""
    template, words = (
        Path(__file__)
        .with_name("prompt.md")
        .read_text(encoding="utf-8")
        .split("\n<!-- labels -->\n", 1)
    )
    labels = json.loads(words)
    return Template(template).substitute(
        goal=params.goal,
        knowledge=params.knowledge or labels["no_knowledge"],
        steps_text=compose("memory_records", MemoryParams(mode="verify", entries=params.entries)),
    )


def history(params: VerifyParams, compose: Compose) -> list[str]:
    """使用同一片段构造 BrainPort 的素材列表。"""
    data = compose(
        "memory_records",
        MemoryParams(mode="verify_entries", entries=params.entries, serialized=True),
    )
    return json.loads(data)
