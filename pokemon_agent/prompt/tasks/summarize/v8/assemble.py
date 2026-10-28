"""summarize v7：共享输出规则与十块布局，保留完整蒸馏原料。"""

import json
from pathlib import Path

from ...budget import BudgetRecord, render_budgets
from ...interfaces.assembly import Compose
from ...records import GoalDefinition
from ..fragments.goal.params import GoalParams
from ..fragments.image_reading.params import ImageReadingParams
from ..fragments.memory_records.params import MemoryParams
from ..fragments.prompt_layout.params import Block, PromptLayoutParams
from .params import SummarizeParams

_RULES, _WORDS = (
    Path(__file__)
    .with_name("prompt.md")
    .read_text(encoding="utf-8")
    .split("\n<!-- labels -->\n", 1)
)
_LABELS = json.loads(_WORDS)


def history(params: SummarizeParams, compose: Compose) -> list[str]:
    """保留逐条全文与相邻帧去重，编号由 memory_records v2 统一生成。"""
    return json.loads(
        compose(
            "memory_records",
            MemoryParams(
                mode="summarize", entries=params.entries, verdicts=params.verdicts, serialized=True
            ),
        )
    )


def _feedback(params: SummarizeParams, compose: Compose) -> str:
    """状态表先于最近判定；空依据不生成占位句。"""
    parts: list[str] = []
    recent = [_LABELS["recent"]]
    recent.append(_LABELS["success"] if params.success else _LABELS["failure"])
    if params.termination:
        recent.append(_LABELS["termination"].format(params.termination))
    if params.judge_reason:
        recent.append(_LABELS["reason"].format(params.judge_reason))
    if len(recent) > 1:
        parts.append("\n".join(recent))
    return "\n\n".join(parts)


def assemble(params: SummarizeParams, compose: Compose) -> str:
    """共享布局负责块序；规则不包含动态目标、历史、判定或额度。"""
    rules = "\n\n".join(
        [
            compose("image_reading", ImageReadingParams(scope="episode")),
            _RULES.strip(),
        ]
    )
    goal = compose("goal", GoalParams(entries=[GoalDefinition(goal=params.goal, criteria="")]))
    budget = render_budgets(
        [
            BudgetRecord(
                kind="hard",
                scope="episode",
                unit="tasks",
                source="max_steps",
                used=params.steps,
                limit=params.max_steps,
            )
        ]
    )
    return compose(
        "prompt_layout",
        PromptLayoutParams(
            blocks={
                Block.RULES: rules,
                Block.GOAL: goal,
                Block.HISTORY: "\n\n".join(history(params, compose)),
                Block.FEEDBACK: _feedback(params, compose),
                Block.BUDGET: budget,
            }
        ),
    )
