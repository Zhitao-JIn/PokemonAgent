"""任务 v2：保留原模板措辞，只装配独立原料。"""

import json
from pathlib import Path
from string import Template

from ...interfaces.assembly import Compose
from ..fragments.memory_records.params import MemoryParams
from .params import SummarizeParams


def assemble(params: SummarizeParams, compose: Compose) -> str:
    """通过注册片段渲染素材，替换模板占位符。"""
    template, words = (
        Path(__file__)
        .with_name("prompt.md")
        .read_text(encoding="utf-8")
        .split("\n<!-- labels -->\n", 1)
    )
    labels = json.loads(words)
    result = labels["success"] if params.success else labels["failure"]
    return Template(template).substitute(
        goal=params.goal,
        steps_text=compose(
            "memory_records",
            MemoryParams(mode="summarize", entries=params.entries, verdicts=params.verdicts),
        ),
        result=labels["result"].format(
            result, params.termination, params.judge_reason or labels["none"]
        ),
        steps=params.steps,
        max_steps=params.max_steps,
    )


def history(params: SummarizeParams, compose: Compose) -> list[str]:
    """使用同一片段构造 BrainPort 的素材列表。"""
    data = compose(
        "memory_records",
        MemoryParams(
            mode="summarize", entries=params.entries, verdicts=params.verdicts, serialized=True
        ),
    )
    return json.loads(data)
