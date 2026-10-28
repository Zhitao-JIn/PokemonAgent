"""judge_success v11：三层共用同构布局，保留完整判定素材。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from string import Template

from ...interfaces.assembly import Compose
from ...ram_observation import RamObservationRecord
from ...records import (
    ActRecord,
    EpisodeRecord,
    GoalRecord,
    RunRecord,
    TaskRecord,
    TaskTableRecord,
)
from ..fragments.goal.params import GoalParams
from ..fragments.goal_table.params import GoalTableParams
from ..fragments.judge_interrupt.params import JudgeInterruptParams
from ..fragments.knowledge.params import KnowledgeParams
from ..fragments.memory_records.params import MemoryParams
from ..fragments.observation.params import ObservationParams
from ..fragments.prompt_layout.params import Block, PromptLayoutParams
from ..fragments.read_screen.params import ReadScreenParams
from ..fragments.task_frame.params import TaskFrameParams
from ..fragments.task_table.params import TaskTableParams
from .params import JudgeParams

_TEXT, _WORDS = (
    Path(__file__)
    .with_name("prompt.md")
    .read_text(encoding="utf-8")
    .split("\n<!-- labels -->\n", 1)
)
_COMMON_RULES, _RUN_RULES = _TEXT.split("\n<!-- run_ram_rules -->\n", 1)
_TEMPLATE = Template(_COMMON_RULES)
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


def _sequence(entries: list[ActRecord], compose: Compose) -> list[str]:
    """相邻帧去重与旧序列保持一致。"""
    return _records(entries, "sequence", compose)


def _goal_table(entries: Sequence[GoalRecord], compose: Compose) -> list[str]:
    """空表不组合片段，非空表保留逐条边界。"""
    if not entries:
        return []
    return json.loads(
        compose("goal_table", GoalTableParams(entries=list(entries), serialized=True))
    )


def _task_table(entries: Sequence[TaskTableRecord], compose: Compose) -> list[str]:
    """空表不组合片段，非空表保留逐条边界。"""
    if not entries:
        return []
    return json.loads(
        compose("task_table", TaskTableParams(entries=list(entries), serialized=True))
    )


def memory_blocks(params: JudgeParams, compose: Compose) -> list[str]:
    """消费独立原料，保留旧措辞、条件与顺序。"""
    blocks: list[str] = []
    if params.goal_table:
        blocks.append(_LABELS["L000"] + "\n".join(_goal_table(params.goal_table, compose)))
    if params.latest_planning is not None:
        blocks.append(
            _LABELS["L001"].format(
                params.trigger, params.planning_round, params.latest_planning.model_dump_json()
            )
        )
    if params.task_table:
        rows = "\n".join(_task_table(params.task_table, compose))
        blocks.append(_LABELS["L002"].format(rows))
    blocks += [_LABELS["L003"].format(m.task_id, _record(m, compose)) for m in params.task_memories]
    blocks += [
        _LABELS["L004"].format(m.episode_id, _record(m, compose)) for m in params.episode_memories
    ]
    if params.task_index:
        rows = "\n".join(_index(memory, compose) for memory in params.task_index)
        blocks.append(_LABELS["L005"].format(rows))
    if params.episode_index:
        rows = "\n".join(_index(memory, compose) for memory in params.episode_index)
        blocks.append(_LABELS["L006"].format(rows))
    if params.run_index:
        rows = "\n".join(_index(memory, compose) for memory in params.run_index)
        blocks.append(_LABELS["L007"].format(rows))
    if params.observation is not None:
        blocks.append(
            _LABELS["L008"].format(
                compose(
                    "observation",
                    ObservationParams(observation=params.observation),
                )
            )
        )
    return blocks


def _ram_observations(entries: Sequence[RamObservationRecord]) -> str:
    """只渲染真实记录及来源，不从摘要推断数值。"""
    return "\n\n".join(
        _LABELS["L013"].format(
            i,
            entry.observed_at,
            entry.sequence,
            entry.source,
            entry.step,
            entry.event_id,
            entry.ram_json,
        )
        for i, entry in enumerate(entries, start=1)
    )


def _rules(params: JudgeParams, compose: Compose) -> str:
    """共用规则在前；层级专用说明只追加在固定规则末尾。"""
    text = _TEMPLATE.substitute(read_screen=compose("read_screen", ReadScreenParams())).rstrip()
    if params.ram_observations:
        text += "\n\n" + _RUN_RULES.strip()
    if params.allow_interrupt:
        text += "\n\n" + compose("judge_interrupt", JudgeInterruptParams())
    return text


def _indices(params: JudgeParams, compose: Compose) -> str:
    """各层背景索引保持原有逐行渲染与来源提示。"""
    blocks: list[str] = []
    for entries, label in (
        (params.task_index, "L005"),
        (params.episode_index, "L006"),
        (params.run_index, "L007"),
    ):
        if entries:
            blocks.append(_LABELS[label].format("\n".join(_index(m, compose) for m in entries)))
    return _LABELS["index_notice"] + "\n\n" + "\n\n".join(blocks) if blocks else ""


def _executed(params: JudgeParams, compose: Compose) -> str:
    """只放执行历史；逐键序列及两级蒸馏记忆的全文与顺序保留。"""
    steps = _sequence(params.history, compose)
    blocks = [
        _LABELS["L009"].format(entry.step, rendered)
        for entry, rendered in zip(params.history, steps, strict=True)
    ]
    blocks += [_LABELS["L003"].format(m.task_id, _record(m, compose)) for m in params.task_memories]
    blocks += [
        _LABELS["L004"].format(m.episode_id, _record(m, compose)) for m in params.episode_memories
    ]
    return "\n\n".join(blocks)


def _feedback(params: JudgeParams, compose: Compose) -> str:
    """状态表和最新规划主张不混入执行证据；规划 JSON 原样完整输出。"""
    blocks: list[str] = []
    if params.goal_table:
        blocks.append(_LABELS["L000"] + "\n".join(_goal_table(params.goal_table, compose)))
    if params.task_table:
        blocks.append(_LABELS["L002"].format("\n".join(_task_table(params.task_table, compose))))
    if params.latest_planning is not None:
        blocks.append(
            _LABELS["L001"].format(
                params.trigger, params.planning_round, params.latest_planning.model_dump_json()
            )
        )
    return "\n\n".join(blocks)


def _current(params: JudgeParams, compose: Compose) -> str:
    """保留显式当前观测；RAM 窗口在观测之后，无读数则不产生子项。"""
    parts: list[str] = []
    if params.observation is not None:
        parts.append(compose("task_frame", TaskFrameParams(observation=params.observation)))
    if params.ram_observations:
        parts.append(_LABELS["ram_title"] + "\n\n" + _ram_observations(params.ram_observations))
    return "\n\n".join(parts)


def assemble(params: JudgeParams, compose: Compose) -> str:
    """只准备各块正文；统一标题与块序完全由 prompt_layout 决定。"""
    blocks: dict[Block, str] = {
        Block.RULES: _rules(params, compose),
        Block.GOAL: compose("goal", GoalParams(entries=[params.goal])),
        Block.KNOWLEDGE: compose("knowledge", KnowledgeParams(entries=[params.knowledge]))
        if params.knowledge
        else "",
        Block.INDEX: _indices(params, compose),
        Block.OBJECTS: "",
        Block.HISTORY: _executed(params, compose),
        Block.FEEDBACK: _feedback(params, compose),
        Block.FRAME: _current(params, compose),
    }
    return compose("prompt_layout", PromptLayoutParams(blocks=blocks))


def history(params: JudgeParams, compose: Compose) -> list[str]:
    """BrainPort 仍接收完整单条历史与上层记忆块。"""
    return _records(params.history, "plain", compose) + memory_blocks(params, compose)
