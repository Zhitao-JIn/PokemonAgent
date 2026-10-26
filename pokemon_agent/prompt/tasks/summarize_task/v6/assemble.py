"""summarize_task v6：逐字段填写对象，避免无键名的位置值与相邻数组。"""

import json
from pathlib import Path
from string import Template

from ...interfaces.assembly import Compose
from ..fragments.memory_records.params import MemoryParams
from .params import SummarizeTaskParams


def assemble(params: SummarizeTaskParams, compose: Compose) -> str:
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
        task_id=params.task_id,
        steps_text=compose(
            "memory_records",
            MemoryParams(mode="summarize_task", entries=params.entries, verdicts=params.verdicts),
        ),
        result=labels["result"].format(
            result, params.termination, params.judge_reason or labels["none"]
        ),
        steps=params.steps_used,
        max_steps=params.max_steps,
    )


def history(params: SummarizeTaskParams, compose: Compose) -> list[str]:
    """使用同一片段构造 BrainPort 的素材列表。"""
    data = compose(
        "memory_records",
        MemoryParams(
            mode="summarize_task", entries=params.entries, verdicts=params.verdicts, serialized=True
        ),
    )
    return json.loads(data)
