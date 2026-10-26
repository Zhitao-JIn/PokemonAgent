"""summarize_run v4：JSON闭合与简明证据，动态原料保持不变。"""

import json
from pathlib import Path
from string import Template

from ...interfaces.assembly import Compose
from ..fragments.memory_records.params import MemoryParams
from .params import SummarizeRunParams


def assemble(params: SummarizeRunParams, compose: Compose) -> str:
    """通过注册片段渲染素材，替换模板占位符。"""
    template, words = (
        Path(__file__)
        .with_name("prompt.md")
        .read_text(encoding="utf-8")
        .split("\n<!-- labels -->\n", 1)
    )
    labels = json.loads(words)
    assert params.episode_memories
    goals = "\n".join(
        labels["goal"].format(
            entry.task.task_id,
            entry.task.goal,
            entry.status,
            entry.note,
            str(entry.overturned).lower(),
        )
        for entry in params.goals
    )
    return Template(template).substitute(
        run_goal=params.run_goal,
        termination=params.termination,
        judge_reason=params.judge_reason or labels["none"],
        episodes=params.episodes,
        succeeded=params.succeeded,
        acts_used=params.acts_used,
        max_episodes=params.max_episodes,
        goals=goals or labels["no_goals"],
        episodes_text=compose(
            "memory_records", MemoryParams(mode="summarize_run", entries=params.episode_memories)
        ),
    )


def history(params: SummarizeRunParams, compose: Compose) -> list[str]:
    """使用同一片段构造 BrainPort 的素材列表。"""
    data = compose(
        "memory_records",
        MemoryParams(mode="summarize_run", entries=params.episode_memories, serialized=True),
    )
    return json.loads(data)
