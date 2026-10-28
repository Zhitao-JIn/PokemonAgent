"""decompose v11：共享布局与完整素材。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from string import Template

from ...budget import render_budgets
from ...interfaces.assembly import Compose
from ...records import (
    ActRecord,
    EpisodeRecord,
    JudgeFeedbackRecord,
    RunRecord,
    TaskRecord,
    TaskTableRecord,
)
from ..fragments.goal.params import GoalParams
from ..fragments.human_note.params import HumanNoteParams
from ..fragments.knowledge.params import KnowledgeParams
from ..fragments.last_judge.params import LastJudgeParams
from ..fragments.memory_records.params import MemoryParams
from ..fragments.prompt_layout.params import Block, PromptLayoutParams
from ..fragments.task_frame.params import TaskFrameParams
from ..fragments.task_table.params import TaskTableParams
from ..fragments.terrain_legend.params import TerrainLegendParams
from .params import DecomposeParams

_TEMPLATE = Template(Path(__file__).with_name("prompt.md").read_text(encoding="utf-8"))


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


def _task_table(entries: Sequence[TaskTableRecord], compose: Compose) -> list[str]:
    """空表不组合片段，非空表保留逐条边界。"""
    if not entries:
        return []
    return json.loads(
        compose("task_table", TaskTableParams(entries=list(entries), serialized=True))
    )


def _last_judge(feedback: JudgeFeedbackRecord, compose: Compose) -> list[str]:
    """判定与人的表态保留原次序。"""
    return json.loads(compose("last_judge", LastJudgeParams(feedback=feedback, serialized=True)))


def _budgets(params: DecomposeParams) -> str:
    """保留额度、规划轮数、派发顺序与新增建议上限。"""
    remaining = (
        str(params.remaining_planning_rounds)
        if params.remaining_planning_rounds is not None
        else "未提供"
    )
    return "\n".join(
        (
            render_budgets(params.budget_context) if params.budget_context else "",
            f"剩余拆解轮数：{remaining}；本次新增建议上限：{params.max_tasks}",
            f"派发顺序：{params.execution_order}",
        )
    ).strip()


def material_blocks(params: DecomposeParams, compose: Compose) -> dict[Block, str]:
    """备齐各块正文，将标题与顺序交给共享布局。"""
    rules = _TEMPLATE.substitute(
        terrain_legend=compose(
            "terrain_legend", TerrainLegendParams(meanings=params.terrain_meanings)
        )
    )
    blocks: dict[Block, str] = {
        Block.RULES: rules,
        Block.GOAL: compose("goal", GoalParams(entries=[params.goal])),
        Block.KNOWLEDGE: compose("knowledge", KnowledgeParams(entries=params.knowledge))
        if params.knowledge
        else "",
        Block.INDEX: "\n".join(_index(entry, compose) for entry in params.episode_index),
        Block.OBJECTS: "",
        Block.HISTORY: "\n\n".join(_record(entry, compose) for entry in params.task_memories),
        Block.FEEDBACK: "\n".join(
            _task_table(params.task_table, compose)
            + (_last_judge(params.last_judge, compose) if params.last_judge is not None else [])
        ),
        Block.FRAME: compose("task_frame", TaskFrameParams(observation=params.observation)),
        Block.BUDGET: _budgets(params),
        Block.HUMAN: compose("human_note", HumanNoteParams(note=params.human_note))
        if params.human_note.strip()
        else "",
    }
    return blocks


def assemble(params: DecomposeParams, compose: Compose) -> str:
    """统一布局是模型文本的唯一标题与排序出口。"""
    return compose("prompt_layout", PromptLayoutParams(blocks=material_blocks(params, compose)))


def history(params: DecomposeParams, compose: Compose) -> list[str]:
    """只产出本层历史与背景索引，不渲染规则或地形图例。"""
    records = _records(params.task_memories, "plain", compose)
    indices = _records(params.episode_index, "index", compose)
    return records + indices
