"""judge_success v10：静态规则不变，五帧RAM无损增量编码。"""

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
from ..fragments.goal_table.params import GoalTableParams
from ..fragments.judge_interrupt.params import JudgeInterruptParams
from ..fragments.memory_records.params import MemoryParams
from ..fragments.observation.params import ObservationParams
from ..fragments.read_screen.params import ReadScreenParams
from ..fragments.task_table.params import TaskTableParams
from .params import JudgeParams

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
                    ObservationParams(
                        observation=params.observation, known_objects=params.known_objects
                    ),
                )
            )
        )
    return blocks


def _ram_observations(entries: Sequence[RamObservationRecord]) -> str:
    """保留五帧来源与读数，用显式无损增量消除相邻重复字段。"""
    if not entries:
        return _LABELS["L012"]
    frames: list[str] = []
    previous: dict | None = None
    for index, entry in enumerate(entries, start=1):
        current = json.loads(entry.ram_json)
        if previous is None:
            payload = {"full": current}
        else:
            changed = {
                key: value
                for key, value in current.items()
                if key not in previous or previous[key] != value
            }
            removed = [key for key in previous if key not in current]
            payload = {"base": index - 1, "set": changed, "remove": removed}
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        frames.append(
            _LABELS["L013"].format(
                index,
                entry.observed_at,
                entry.sequence,
                entry.source,
                entry.step,
                entry.event_id,
                encoded,
            )
        )
        previous = current
    instruction = (
        "RAM无损增量编码：full是该帧完整读数；base引用本窗口上一帧编号，"
        "先复制该帧完整读数，用set替换指定顶层字段，再删除remove中的字段。"
        "未列字段沿用base，不是未知或消失；set中的对象/列表整体替换。"
        "每帧仍是其标注时刻的实际读数，按原判据对齐时间与来源。\n\n"
    )
    encoded_window = instruction + "\n\n".join(frames)
    original = "\n\n".join(
        _LABELS["L013"].format(
            i, e.observed_at, e.sequence, e.source, e.step, e.event_id, e.ram_json
        )
        for i, e in enumerate(entries, start=1)
    )
    return encoded_window if len(encoded_window) < len(original) else original


def assemble(params: JudgeParams, compose: Compose) -> str:
    """消费独立原料，保留旧措辞、条件与顺序。"""
    goal, history = (params.goal, params.history)
    steps = _sequence(list(history), compose)
    past = "\n\n".join(
        (
            _LABELS["L009"].format(entry.step, rendered)
            for entry, rendered in zip(history, steps, strict=True)
        )
    )
    past = "\n\n".join(filter(None, [past, *memory_blocks(params, compose)]))
    return _TEMPLATE.substitute(
        goal=goal.goal,
        ram_observations=_ram_observations(params.ram_observations),
        knowledge=params.knowledge or _LABELS["L010"],
        criteria=goal.criteria,
        history=past or _LABELS["L011"],
        interrupt_rule=compose("judge_interrupt", JudgeInterruptParams())
        if params.allow_interrupt
        else "",
        read_screen=compose("read_screen", ReadScreenParams()),
    )


def history(params: JudgeParams, compose: Compose) -> list[str]:
    """BrainPort 仍接收完整单条历史与上层记忆块。"""
    return _records(params.history, "plain", compose) + memory_blocks(params, compose)
