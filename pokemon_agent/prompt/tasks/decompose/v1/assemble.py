"""任务 v1：按原请求条件组合注册片段。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from string import Template

from ...interfaces.assembly import Compose
from ...records import (
    ActRecord,
    EpisodeRecord,
    JudgeFeedbackRecord,
    RunRecord,
    TaskRecord,
    TaskTableRecord,
)
from ..fragments.human_note.params import HumanNoteParams
from ..fragments.last_judge.params import LastJudgeParams
from ..fragments.memory_records.params import MemoryParams
from ..fragments.observation.params import ObservationParams
from ..fragments.task_table.params import TaskTableParams
from ..fragments.terrain_legend.params import TerrainLegendParams
from .params import DecomposeParams

_TEXT, _WORDS = (
    Path(__file__)
    .with_name("prompt.md")
    .read_text(encoding="utf-8")
    .split("\n<!-- labels -->\n", 1)
)
_TEMPLATE = Template(_TEXT)
_LABELS = json.loads(_WORDS)


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


def _append_note(prompt: str, note: str, compose: Compose) -> str:
    """无插话原样返回，有插话组合最高优先级片段。"""
    return prompt + compose("human_note", HumanNoteParams(note=note)) if note.strip() else prompt


def context_lines(params: DecomposeParams, compose: Compose) -> list[str]:
    """消费独立原料，保留旧措辞、条件与顺序。"""
    remaining = (
        params.remaining_planning_rounds
        if params.remaining_planning_rounds is not None
        else _LABELS["L000"]
    )
    lines = [
        _LABELS["L001"],
        compose("observation", ObservationParams(observation=params.observation)),
        _LABELS["L002"].format(remaining, params.execution_order),
    ]
    if params.task_table:
        lines += ["", _LABELS["L003"], *_task_table(params.task_table, compose)]
    if params.last_judge is not None:
        lines += ["", _LABELS["L004"], *_last_judge(params.last_judge, compose)]
    if params.task_memories:
        lines += ["", _LABELS["L005"], *(_record(m, compose) for m in params.task_memories)]
    if params.episode_index:
        lines += [
            "",
            _LABELS["L006"],
            *(_index(memory, compose) for memory in params.episode_index),
        ]
    lines += ["", _LABELS["L007"], *(params.knowledge or [_LABELS["L008"]])]
    return lines


def assemble(params: DecomposeParams, compose: Compose) -> str:
    """消费独立原料，保留旧措辞、条件与顺序。"""
    return _append_note(
        _TEMPLATE.substitute(
            goal=params.goal.goal,
            criteria=params.goal.criteria,
            context="\n".join(context_lines(params, compose)),
            max_tasks=params.max_tasks,
            terrain_legend=compose(
                "terrain_legend", TerrainLegendParams(meanings=params.terrain_meanings)
            ),
        ),
        params.human_note,
        compose,
    )


def history(params: DecomposeParams, compose: Compose) -> list[str]:
    """BrainPort 的 context 与模型素材同源。"""
    return context_lines(params, compose)
