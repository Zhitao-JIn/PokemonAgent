"""记忆片段 v4 的结构化事实和各层记录渲染。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ....records import ActRecord, EpisodeRecord, RunRecord, TaskRecord

_LABELS = json.loads(
    Path(__file__)
    .with_name("prompt.md")
    .read_text(encoding="utf-8")
    .split("<!-- labels -->\n", 1)[1]
)


def _option_layout(facts: ActRecord.Observation.Facts) -> str:
    """按选项网格与光标位置生成布局。"""
    assert facts.option_grid and facts.cursor_cell is not None
    grid = facts.option_grid
    row, col = facts.cursor_cell
    rows, cols = len(grid), max(len(items) for items in grid)
    if cols == 1:
        head = _LABELS["vertical"].format(rows, row + 1)
    elif rows == 1:
        head = _LABELS["horizontal"].format(cols, col + 1)
    else:
        head = _LABELS["grid"].format(rows, cols, row + 1, col + 1)
    lines = [
        "  ".join(
            (_LABELS["selected"] if (i, j) == facts.cursor_cell else " ") + item
            for j, item in enumerate(items)
        )
        for i, items in enumerate(grid)
    ]
    return head + "\n" + "\n".join(lines)


def task_render(self: TaskRecord) -> str:
    """保留既有字段顺序与条件，仅转换独立原料。"""
    mark = (
        _LABELS["L023"]
        if self.success
        else _LABELS["L025"].format(self.termination or _LABELS["L024"])
    )
    lines = [
        _LABELS["L026"].format(
            self.task_id,
            self.goal,
            mark,
            self.total_acts,
            self.total_acts + self.steps_used - 1,
            self.steps_used,
        )
    ]
    if self.reason:
        lines.append(_LABELS["L027"].format(self.reason))
    lines.append(_LABELS["L028"].format(self.summary))
    for label, items in (
        (_LABELS["L029"], self.reusable_patterns),
        (_LABELS["L030"], self.critical_decisions),
        (_LABELS["L031"], self.failure_points),
    ):
        for item in items:
            lines.append(_LABELS["L032"].format(label, item))
    if self.quality_rationale:
        lines.append(
            _LABELS["L033"].format(format(self.quality_score, ".2f"), self.quality_rationale)
        )
    return "\n".join(lines)


def episode_render(self: EpisodeRecord) -> str:
    """保留既有字段顺序与条件，仅转换独立原料。"""
    lines = [
        _LABELS["L036"].format(
            self.episode_id,
            self.goal,
            _LABELS["L034"] if self.success else _LABELS["L035"],
            _LABELS["comma"] + self.termination if self.termination else "",
            self.steps,
            self.acts_used,
        )
    ]
    if self.reason:
        lines.append(_LABELS["L037"].format(self.reason))
    if not self.summary.strip():
        lines.append(_LABELS["L038"].format(self.quality_rationale))
        return "\n".join(lines)
    lines.append(_LABELS["L039"].format(self.summary))
    if self.reusable_patterns:
        lines.append(_LABELS["L040"] + "；".join(self.reusable_patterns))
    if self.critical_decisions:
        lines.append(_LABELS["L041"] + "；".join(self.critical_decisions))
    if self.failure_points:
        lines.append(_LABELS["L042"] + "；".join(self.failure_points))
    lines.append(_LABELS["L043"].format(format(self.quality_score, ".2f"), self.quality_rationale))
    if self.tags:
        lines.append(_LABELS["L044"] + "、".join(self.tags))
    return "\n".join(lines)


def run_render(self: RunRecord) -> str:
    """保留既有字段顺序与条件，仅转换独立原料。"""
    lines = [
        _LABELS["L047"].format(
            self.run_id,
            self.run_goal,
            _LABELS["L045"] if self.success else _LABELS["L046"],
            _LABELS["comma"] + self.termination if self.termination else "",
            self.succeeded,
            self.episodes,
            self.acts_used,
        )
    ]
    if self.reason:
        lines.append(_LABELS["L048"].format(self.reason))
    if not self.summary.strip():
        lines.append(_LABELS["L049"].format(self.quality_rationale))
        return "\n".join(lines)
    lines.append(_LABELS["L050"].format(self.summary))
    if self.reusable_patterns:
        lines.append(_LABELS["L051"] + "；".join(self.reusable_patterns))
    if self.critical_decisions:
        lines.append(_LABELS["L052"] + "；".join(self.critical_decisions))
    if self.failure_points:
        lines.append(_LABELS["L053"] + "；".join(self.failure_points))
    lines.append(_LABELS["L054"].format(format(self.quality_score, ".2f"), self.quality_rationale))
    if self.tags:
        lines.append(_LABELS["L055"] + "、".join(self.tags))
    return "\n".join(lines)


def snapshot_facts(
    obs: ActRecord.Observation, *, include_terrain: bool = False
) -> ActRecord.Observation.Facts:
    """优先从同帧原料投影；旧记忆缺少增量字段时保留其已有文本。"""
    facts = obs.facts.model_copy()
    if not include_terrain:
        facts.walk_map = ""
    elif facts.cells and obs.place is not None:
        facts.walk_map = terrain_render(facts.cells, obs.place) if facts.terrain_visible else ""
    if obs.place is not None:
        place = obs.place
        facts.where = _LABELS["location"].format(place.map_id, place.x, place.y)
    if "neighbor_cells" in facts.model_fields_set:
        cells = facts.neighbor_cells
        facts.neighbors = (
            _LABELS["neighbors"].format(cells["up"], cells["down"], cells["left"], cells["right"])
            if cells
            else ""
        )
    updates: dict[str, Any] = {}
    if "option_grid" in facts.model_fields_set:
        updates["option_layout"] = ""
    if "option_annotations" in facts.model_fields_set:
        updates["option_details"] = ""
    if "battle_status" in facts.model_fields_set and facts.battle_status is None:
        updates.update(
            {
                prefix + "_" + name: ""
                for prefix in ("my", "foe")
                for name in ("name", "level", "hp", "status")
            }
        )
    if facts.option_grid and facts.cursor_cell is not None:
        updates["option_layout"] = _option_layout(facts)
    if facts.option_annotations:
        updates["option_details"] = " / ".join(
            option + " " + detail
            for option, detail in zip(facts.options, facts.option_annotations, strict=False)
            if detail
        )
    if facts.battle_status is not None:
        for prefix, side in (("my", facts.battle_status.mine), ("foe", facts.battle_status.foe)):
            updates[prefix + "_name"] = side.name
            updates[prefix + "_level"] = str(side.level)
            updates[prefix + "_hp"] = str(side.hp) + "/" + str(side.max_hp)
            updates[prefix + "_status"] = side.status
    return facts.model_copy(update=updates)


def task_index(self: TaskRecord) -> str:
    """按原条件和顺序渲染独立原料。"""
    return _LABELS["L071"].format(
        self.task_id,
        self.goal,
        _LABELS["L069"] if self.success else _LABELS["L070"],
        self.termination or "-",
        self.steps_used,
        first_sentence(self.summary),
    )


def episode_index(self: EpisodeRecord) -> str:
    """按原条件和顺序渲染独立原料。"""
    return _LABELS["L074"].format(
        self.episode_id,
        self.goal,
        _LABELS["L072"] if self.success else _LABELS["L073"],
        self.termination or "-",
        self.steps,
        self.acts_used,
        first_sentence(self.summary),
    )


def run_index(self: RunRecord) -> str:
    """按原条件和顺序渲染独立原料。"""
    return _LABELS["L075"].format(
        self.run_id,
        self.run_goal,
        self.succeeded,
        self.episodes,
        self.termination or "-",
        first_sentence(self.summary),
    )


def first_sentence(text: str) -> str:
    """按原条件和顺序渲染独立原料。"""
    sentence = text.strip()
    for index, character in enumerate(sentence):
        if character in _LABELS["L076"]:
            sentence = sentence[: index + 1]
            break
        if character in "\r\n":
            sentence = sentence[:index]
            break
    sentence = sentence.strip()
    if not sentence:
        return _LABELS["L077"]
    return sentence[:80] + _LABELS["L078"] if len(sentence) > 80 else sentence


def terrain_render(cells: list[str], place: ActRecord.Observation.Place) -> str:
    """固定九行十列，行号和行尾范围使用全局坐标。"""
    assert len(cells) == 9 and all(len(line) == 10 for line in cells)
    ys = [place.y + row - 4 for row in range(9)]
    left, right = place.x - 4, place.x + 5
    gutter = max(len(str(y)) for y in ys)
    lines = [_LABELS["terrain_header"]]
    for row, line in enumerate(cells):
        chars = list(line)
        if row == 4:
            chars[4] = "@"
        lines.append(
            _LABELS["terrain_row"].format(str(ys[row]).ljust(gutter), "".join(chars), left, right)
        )
    return "\n".join(lines)
