"""summarize_run v6：共享输出规则与十块布局，保留完整蒸馏原料。"""

import json
from pathlib import Path

from ...budget import BudgetRecord, render_budgets
from ...interfaces.assembly import Compose
from ...records import GoalDefinition
from ..fragments.distill_output.params import DistillOutputParams
from ..fragments.goal.params import GoalParams
from ..fragments.goal_table.params import GoalTableParams
from ..fragments.image_reading.params import ImageReadingParams
from ..fragments.memory_records.params import MemoryParams
from ..fragments.prompt_layout.params import Block, PromptLayoutParams
from .params import SummarizeRunParams

_RULES, _WORDS = (
    Path(__file__)
    .with_name("prompt.md")
    .read_text(encoding="utf-8")
    .split("\n<!-- labels -->\n", 1)
)
_LABELS = json.loads(_WORDS)


def history(params: SummarizeRunParams, compose: Compose) -> list[str]:
    """保留逐条全文与相邻帧去重，编号由 memory_records v2 统一生成。"""
    return json.loads(
        compose(
            "memory_records",
            MemoryParams(mode="summarize", entries=params.episode_memories, serialized=True),
        )
    )


def _feedback(params: SummarizeRunParams, compose: Compose) -> str:
    """状态表先于最近判定；空依据不生成占位句。"""
    parts: list[str] = []
    if params.goals:
        parts.append(
            _LABELS["goals"] + "\n" + compose("goal_table", GoalTableParams(entries=params.goals))
        )
    recent = [_LABELS["recent"]]
    if params.termination:
        recent.append(_LABELS["termination"].format(params.termination))
    if params.judge_reason:
        recent.append(_LABELS["reason"].format(params.judge_reason))
    if len(recent) > 1:
        parts.append("\n".join(recent))
    return "\n\n".join(parts)


def assemble(params: SummarizeRunParams, compose: Compose) -> str:
    """共享布局负责块序；规则不包含动态目标、历史、判定或额度。"""
    rules = "\n\n".join(
        [
            compose("distill_output", DistillOutputParams(scope="run")),
            compose("image_reading", ImageReadingParams(scope="run")),
            _RULES.strip(),
        ]
    )
    goal = compose("goal", GoalParams(entries=[GoalDefinition(goal=params.run_goal, criteria="")]))
    budget = render_budgets(
        [
            BudgetRecord(
                kind="hard",
                scope="run",
                unit="episodes",
                source="max_episodes",
                used=params.episodes,
                limit=params.max_episodes,
            )
        ]
    )
    assert params.episode_memories, "Run distillation requires episode history"
    budget += "\n" + _LABELS["counts"].format(params.succeeded, params.acts_used)
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
