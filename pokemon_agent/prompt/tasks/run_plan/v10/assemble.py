"""run_plan v10：共享布局与完整素材。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from ...budget import render_budgets
from ...interfaces.assembly import Compose
from ...records import (
    ActRecord,
    EpisodeRecord,
    GoalRecord,
    JudgeFeedbackRecord,
    RunRecord,
    TaskRecord,
)
from ..fragments.goal.params import GoalParams
from ..fragments.goal_table.params import GoalTableParams
from ..fragments.human_note.params import HumanNoteParams
from ..fragments.knowledge.params import KnowledgeParams
from ..fragments.last_judge.params import LastJudgeParams
from ..fragments.memory_records.params import MemoryParams
from ..fragments.prompt_layout.params import Block, PromptLayoutParams
from ..fragments.task_frame.params import TaskFrameParams
from ..fragments.terrain_legend.params import TerrainLegendParams
from .params import RunPlanParams

_TEXT = Path(__file__).with_name("prompt.md").read_text(encoding="utf-8")


def _records(
    entries: Sequence[ActRecord | TaskRecord | EpisodeRecord | RunRecord],
    mode: str,
    compose: Compose,
) -> list[str]:
    """保留版本片段返回的逐条边界。"""
    return json.loads(
        compose("memory_records", MemoryParams(mode=mode, entries=list(entries), serialized=True))
    )


def _record(entry: ActRecord | TaskRecord | EpisodeRecord | RunRecord, compose: Compose) -> str:
    """单条正文，不省略相邻快照或结果。"""
    return _records([entry], "plain", compose)[0]


def _index(entry: TaskRecord | EpisodeRecord | RunRecord, compose: Compose) -> str:
    """一行背景索引。"""
    return _records([entry], "index", compose)[0]


def _goal_table(entries: Sequence[GoalRecord], compose: Compose) -> list[str]:
    """空表不组合片段，非空表保留逐条边界。"""
    if not entries:
        return []
    return json.loads(
        compose("goal_table", GoalTableParams(entries=list(entries), serialized=True))
    )


def _last_judge(feedback: JudgeFeedbackRecord, compose: Compose) -> list[str]:
    """判定与人的表态保留原次序。"""
    return json.loads(compose("last_judge", LastJudgeParams(feedback=feedback, serialized=True)))


def detail_blocks(details: Sequence[EpisodeRecord], compose: Compose) -> list[str]:
    """消费独立原料，保留旧措辞、条件与顺序。"""
    return [_record(memory, compose) for memory in details]


def run_index_lines(memories: Sequence[RunRecord], compose: Compose) -> list[str]:
    """消费独立原料，保留旧措辞、条件与顺序。"""
    return [_index(memory, compose) for memory in memories]


def history_blocks(params: RunPlanParams, compose: Compose) -> list[str]:
    """消费独立原料，保留旧措辞、条件与顺序。"""
    blocks = detail_blocks(params.details, compose)
    background = run_index_lines(params.run_index, compose)
    return blocks + background


def _budgets(params: RunPlanParams) -> str:
    """保留额度、规划轮数、派发顺序与新增建议上限。"""
    remaining = (
        str(params.remaining_planning_rounds)
        if params.remaining_planning_rounds is not None
        else "未提供"
    )
    return "\n".join(
        (
            render_budgets(params.budget_context) if params.budget_context else "",
            f"剩余规划轮数：{remaining}；本次新增建议上限：{params.max_push}",
            f"当前派发顺序：{params.execution_order}",
        )
    ).strip()


def assemble(params: RunPlanParams, compose: Compose) -> str:
    """备齐各块正文，将标题与顺序交给共享布局。"""
    rules = _TEXT.strip()
    if params.terrain_meanings:
        rules += "\n\n" + compose(
            "terrain_legend", TerrainLegendParams(meanings=params.terrain_meanings)
        )
    blocks: dict[Block, str] = {
        Block.RULES: rules,
        Block.GOAL: compose("goal", GoalParams(entries=[params.run_goal])),
        Block.KNOWLEDGE: compose("knowledge", KnowledgeParams(entries=params.knowledge))
        if params.knowledge
        else "",
        Block.INDEX: "\n".join(run_index_lines(params.run_index, compose)),
        Block.OBJECTS: "",
        Block.HISTORY: "\n\n".join(detail_blocks(params.details, compose)),
        Block.FEEDBACK: "\n".join(
            _goal_table(params.plan, compose)
            + (_last_judge(params.last_judge, compose) if params.last_judge is not None else [])
        ),
        Block.FRAME: compose("task_frame", TaskFrameParams(observation=params.observation))
        if params.observation is not None
        else "",
        Block.BUDGET: _budgets(params),
        Block.HUMAN: compose("human_note", HumanNoteParams(note=params.human_note))
        if params.human_note.strip()
        else "",
    }
    return compose("prompt_layout", PromptLayoutParams(blocks=blocks))


def history(params: RunPlanParams, compose: Compose) -> list[str]:
    """BrainPort 的历史块与模板同源。"""
    return history_blocks(params, compose)


def goals(params: RunPlanParams, compose: Compose) -> list[str]:
    """BrainPort 目标表与模型目标表同源。"""
    return _goal_table(params.plan, compose)
