"""记忆片段 v1：原料渲染与相邻快照去重。"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any

from ....interfaces.assembly import Compose
from ....records import ActRecord, EpisodeRecord, RunRecord, TaskRecord
from .params import MemoryParams

_LABELS = json.loads(
    Path(__file__)
    .with_name("prompt.md")
    .read_text(encoding="utf-8")
    .split("<!-- labels -->\n", 1)[1]
)
_EXTRA_ORDER = ("my_name", "my_level", "my_hp", "foe_name", "foe_level", "foe_hp")


def _display_width(text: str) -> int:
    """保留既有字段顺序与条件，仅转换独立原料。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def landmark_render(self: ActRecord.Observation.Facts.Landmark) -> str:
    """保留既有字段顺序与条件，仅转换独立原料。"""
    return _LABELS["L000"].format(self.kind, self.x, self.y)


def facts_entries(self: ActRecord.Observation.Facts) -> list[tuple[str, str, str]]:
    """保留既有字段顺序与条件，仅转换独立原料。"""
    entries: list[tuple[str, str, str]] = []
    if self.scene is not None:
        entries.append(("scene", _LABELS["L001"], self.scene))
    if self.overlay is not None:
        entries.append(("overlay", _LABELS["L002"], self.overlay))
    if self.where:
        entries.append(("where", _LABELS["L003"], self.where))
    if self.map_id is not None:
        entries.append(("map_id", _LABELS["L004"], str(self.map_id)))
    if self.facing:
        entries.append(("facing", _LABELS["L005"], self.facing))
    if self.neighbors:
        entries.append(("neighbors", _LABELS["L006"], self.neighbors))
    if self.landmarks:
        entries.append(
            ("landmarks", _LABELS["L007"], "; ".join(landmark_render(m) for m in self.landmarks))
        )
    if self.dialog_text:
        entries.append(("dialog_text", _LABELS["L008"], self.dialog_text))
    if self.options:
        entries.append(("options", _LABELS["L009"], " / ".join(self.options)))
    if self.cursor:
        entries.append(("cursor", _LABELS["L010"], self.cursor))
    extra: dict[str, Any] = self.model_extra or {}
    seen = set()
    for k in _EXTRA_ORDER:
        if k in extra and extra[k] not in (None, ""):
            entries.append((k, k, str(extra[k])))
            seen.add(k)
    for k in sorted(extra):
        if k in seen or extra[k] in (None, ""):
            continue
        entries.append((k, k, str(extra[k])))
    if self.overview:
        entries.append(("overview", _LABELS["L011"], self.overview))
    if self.walk_map:
        entries.append(("walk_map", "walk_map", self.walk_map))
    if self.screen:
        entries.append(("screen", _LABELS["L012"], "\n" + self.screen))
    return entries


def facts_render(self: ActRecord.Observation.Facts, indent: str = "  ") -> str:
    """保留既有字段顺序与条件，仅转换独立原料。"""
    entries = facts_entries(self)
    if not entries:
        return ""
    width = max((_display_width(label) for _k, label, _v in entries))
    lines = []
    for _k, label, body in entries:
        pad = " " * (width - _display_width(label) + 2)
        gutter = " " * (len(indent) + width + 2)
        body = body.replace("\n", "\n" + gutter)
        lines.append(_LABELS["L013"].format(indent, label, pad, body))
    return "\n".join(lines)


def observation_render(self: ActRecord.Observation, indent: str = "  ") -> str:
    """保留既有字段顺序与条件，仅转换独立原料。"""
    body = facts_render(self.facts, indent)
    text = body if body else _LABELS["L014"].format(indent, self.status) if self.status else ""
    return text


def act_render(self: ActRecord) -> str:
    """保留既有字段顺序与条件，仅转换独立原料。"""
    lines = [
        _LABELS["L015"].format(self.episode_id, self.step),
        render_obs(self.before),
        _LABELS["L016"].format(self.action),
        *([_LABELS["L017"].format(self.result)] if self.result else []),
        _LABELS["L018"] + render_obs(self.after),
    ]
    return "\n".join(lines)


def render_obs(obs: ActRecord.Observation) -> str:
    """保留既有字段顺序与条件，仅转换独立原料。"""
    facts = snapshot_facts(obs)
    return observation_render(obs.model_copy(update={"facts": facts}))


def snapshot_equal(a: ActRecord.Observation, b: ActRecord.Observation) -> bool:
    """保留既有字段顺序与条件，仅转换独立原料。"""
    return a.model_copy(update={"step": 0}) == b.model_copy(update={"step": 0})


def act_sequence(entries: list[ActRecord]) -> list[str]:
    """保留既有字段顺序与条件，仅转换独立原料。"""
    rendered: list[str] = []
    prev: ActRecord | None = None
    for entry in entries:
        if (
            prev is not None
            and prev.step + 1 == entry.step
            and snapshot_equal(prev.after, entry.before)
        ):
            before_block = _LABELS["L019"].format(entry.episode_id, entry.step)
        else:
            before_block = _LABELS["L020"].format(entry.episode_id, entry.step) + render_obs(
                entry.before
            )
        lines = [
            before_block,
            _LABELS["L021"].format(entry.action),
            _LABELS["L022"] + render_obs(entry.after),
        ]
        rendered.append("\n".join(lines))
        prev = entry
    return rendered


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


def assemble(params: MemoryParams, compose: Compose) -> str:
    """按素材种类渲染，再执行任务需要的编号或标注。"""
    if params.mode == "facts":
        assert params.observation is not None
        return json.dumps(
            {
                key: value
                for key, _label, value in facts_entries(
                    snapshot_facts(params.observation, include_terrain=True)
                )
            },
            ensure_ascii=False,
        )
    if params.mode == "observation":
        assert params.observation is not None
        obs = params.observation
        return observation_render(
            obs.model_copy(update={"facts": snapshot_facts(obs, include_terrain=True)})
        )
    entries = params.entries
    if params.mode == "index":
        records = []
        for entry in entries:
            if isinstance(entry, TaskRecord):
                records.append(task_index(entry))
            elif isinstance(entry, EpisodeRecord):
                records.append(episode_index(entry))
            elif isinstance(entry, RunRecord):
                records.append(run_index(entry))
            else:
                raise AssertionError("Index requires task, episode, or run records")
        return json.dumps(records, ensure_ascii=False) if params.serialized else "\n".join(records)
    if entries and isinstance(entries[0], ActRecord):
        acts = [entry for entry in entries if isinstance(entry, ActRecord)]
        records = (
            [act_render(entry) for entry in acts]
            if params.mode in ("verify_entries", "plain")
            else act_sequence(acts)
        )
    else:
        records = []
        for entry in entries:
            if isinstance(entry, TaskRecord):
                records.append(task_render(entry))
            elif isinstance(entry, EpisodeRecord):
                records.append(episode_render(entry))
            elif isinstance(entry, RunRecord):
                records.append(run_render(entry))
    if params.mode == "verify":
        records = [_LABELS["numbered"].format(i, text) for i, text in enumerate(records)]
    elif params.mode in ("summarize", "summarize_task"):
        by_index = {verdict.index: verdict for verdict in params.verdicts}
        blocks: list[str] = []
        for i, text in enumerate(records):
            verdict = by_index.get(i)
            if verdict is None:
                tag = _LABELS["unverified"]
            else:
                key = "positive" if verdict.positive else "negative"
                tag = _LABELS[key].format(verdict.why)
            blocks.append(_LABELS["labeled"].format(i, tag, text))
        records = blocks
    if params.serialized:
        return json.dumps(records, ensure_ascii=False)
    return "\n\n".join(records) or _LABELS["empty"]


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
        updates["option_layout"] = head + "\n" + "\n".join(lines)
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
