"""run_plan v3：仅调整布局，保留原料与规则。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from string import Template

from ...budget import render_budgets
from ...interfaces.assembly import Compose
from ...objects import ObjectFactEvent
from ...records import (
    ActRecord,
    EpisodeRecord,
    GoalRecord,
    JudgeFeedbackRecord,
    RunRecord,
    TaskRecord,
)
from ..fragments.goal_table.params import GoalTableParams
from ..fragments.human_note.params import HumanNoteParams
from ..fragments.last_judge.params import LastJudgeParams
from ..fragments.memory_records.params import MemoryParams
from ..fragments.object_events.params import ObjectEventsParams
from ..fragments.observation.params import ObservationParams
from .params import RunPlanParams

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


def _append_note(prompt: str, note: str, compose: Compose) -> str:
    """无插话原样返回，有插话组合最高优先级片段。"""
    return prompt + compose("human_note", HumanNoteParams(note=note)) if note.strip() else prompt


def _events(events: Sequence[ObjectFactEvent], compose: Compose) -> str:
    """空事件不产生文本；非空事件按步号稳定排版。"""
    return compose("object_events", ObjectEventsParams(events=list(events))) if events else ""


def detail_blocks(details: Sequence[EpisodeRecord], compose: Compose) -> list[str]:
    """消费独立原料，保留旧措辞、条件与顺序。"""
    return [_record(memory, compose) for memory in details]


def run_index_lines(memories: Sequence[RunRecord], compose: Compose) -> list[str]:
    """消费独立原料，保留旧措辞、条件与顺序。"""
    return [_index(memory, compose) for memory in memories]


def object_lines(objects: Sequence[ObjectFactEvent], compose: Compose) -> list[str]:
    """消费独立原料，保留旧措辞、条件与顺序。"""
    rendered = _events(objects, compose)
    return rendered.splitlines() if rendered else []


def history_blocks(params: RunPlanParams, compose: Compose) -> list[str]:
    """消费独立原料，保留旧措辞、条件与顺序。"""
    blocks = detail_blocks(params.details, compose)
    background = run_index_lines(params.run_index, compose)
    objects = object_lines(params.objects, compose)
    if background:
        blocks += ["", _LABELS["L000"], *background]
    if objects:
        blocks += ["", _LABELS["L001"], *objects]
    return blocks


def assemble(params: RunPlanParams, compose: Compose) -> str:
    """消费独立原料，保留旧措辞、条件与顺序。"""
    background = run_index_lines(params.run_index, compose)
    details = detail_blocks(params.details, compose)
    objects = object_lines(params.objects, compose)
    goals = _goal_table(params.plan, compose)
    judged = _last_judge(params.last_judge, compose) if params.last_judge is not None else []
    return _append_note(
        _TEMPLATE.substitute(
            budgets=render_budgets(params.budget_context),
            details="\n\n".join(details) if details else _LABELS["L002"],
            run_index="\n".join(background) if background else _LABELS["L003"],
            knowledge="\n\n".join(params.knowledge) if params.knowledge else _LABELS["L004"],
            observation=compose("observation", ObservationParams(observation=params.observation))
            if params.observation is not None
            else _LABELS["L005"],
            objects="\n".join(objects) if objects else _LABELS["L006"],
            goals="\n".join(goals) if goals else _LABELS["L007"],
            last_judge="\n".join(judged) if judged else _LABELS["L008"],
            max_push=params.max_push,
            parent_goal=params.run_goal.goal,
            parent_criteria=params.run_goal.criteria,
            planning_budget=str(params.remaining_planning_rounds)
            if params.remaining_planning_rounds is not None
            else _LABELS["L009"],
            execution_order=str(params.execution_order),
        ),
        params.human_note,
        compose,
    )


def history(params: RunPlanParams, compose: Compose) -> list[str]:
    """BrainPort 的历史块与模板同源。"""
    return history_blocks(params, compose)


def goals(params: RunPlanParams, compose: Compose) -> list[str]:
    """BrainPort 目标表与模型目标表同源。"""
    return _goal_table(params.plan, compose)
