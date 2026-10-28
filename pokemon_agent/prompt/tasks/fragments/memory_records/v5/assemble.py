"""记忆片段 v5：渲染脚本结局与逐键观察的机械差异。"""

from __future__ import annotations

import json
import unicodedata
from hashlib import sha256
from pathlib import Path
from typing import Any

from ....interfaces.assembly import Compose
from ....loading import load_source
from ....records import ActRecord, EpisodeRecord, IndexRecord, RunRecord, TaskRecord
from .params import MemoryParams

_LABELS = json.loads(
    Path(__file__)
    .with_name("prompt.md")
    .read_text(encoding="utf-8")
    .split("<!-- labels -->\n", 1)[1]
)
_EXTRA_ORDER = ("my_name", "my_level", "my_hp", "foe_name", "foe_level", "foe_hp")
_HELPER_HASH = "b2e6b4e6ed3e1c3df259048e2e10f7c708954ad348f8e546c74c705323fef93c"
_HELPER_PATH = Path(__file__).with_name("render_helpers.py")
if sha256(_HELPER_PATH.read_bytes().replace(b"\r\n", b"\n")).hexdigest() != _HELPER_HASH:
    raise ValueError("memory_records v5 helper hash mismatch")
_HELPERS = load_source(f"{__package__}._render_helper_{_HELPER_HASH}", _HELPER_PATH)
task_render = _HELPERS.task_render
episode_render = _HELPERS.episode_render
run_render = _HELPERS.run_render
snapshot_facts = _HELPERS.snapshot_facts


def _index_tail(index: IndexRecord) -> str:
    """没有 headline（空章）时渲染（无正文），不回退摘要首句。"""
    if not index.headline:
        return _LABELS["L077"]
    return f"{index.headline}（keys：{'、'.join(index.keys)}；含：{'、'.join(index.evidence)}）"


def task_index(item: TaskRecord) -> str:
    return _LABELS["L071"].format(
        item.task_id,
        item.goal,
        _LABELS["L069"] if item.success else _LABELS["L070"],
        item.termination or "-",
        item.steps_used,
        _index_tail(item.index),
    )


def episode_index(item: EpisodeRecord) -> str:
    return _LABELS["L074"].format(
        item.episode_id,
        item.goal,
        _LABELS["L072"] if item.success else _LABELS["L073"],
        item.termination or "-",
        item.steps,
        item.acts_used,
        _index_tail(item.index),
    )


def run_index(item: RunRecord) -> str:
    return _LABELS["L075"].format(
        item.run_id,
        item.run_goal,
        item.succeeded,
        item.episodes,
        item.termination or "-",
        _index_tail(item.index),
    )


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


def script_render(entry: ActRecord) -> list[str]:
    """按相邻观察生成全部变化行，并呈现结构化结局。"""
    lines: list[str] = []
    if entry.outcome is not None:
        outcome = entry.outcome
        lines.append(
            _LABELS["outcome"].format(outcome.code, outcome.ok, outcome.summary, outcome.reason)
        )
    for change in entry.changes:
        place = change.place
        location = f"{place.map_id}:{place.x}:{place.y}" if place else "-"
        obj = change.object.kind if change.object else "-"
        lines.append(_LABELS["change"].format(change.step, change.kind, location, obj, change.text))
    return lines


def act_render(self: ActRecord) -> str:
    """保留既有字段顺序与条件，仅转换独立原料。"""
    lines = [
        _LABELS["L015"].format(self.episode_id, self.step),
        render_obs(self.before),
        _LABELS["L016"].format(self.action),
        *script_render(self),
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
    """按相邻帧去重并呈现每条脚本结局和观察变化。"""
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
            *script_render(entry),
            _LABELS["L022"] + render_obs(entry.after),
        ]
        rendered.append("\n".join(lines))
        prev = entry
    return rendered


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
    records = _render_entries(params)
    records = _label_entries(params, records)
    if params.serialized:
        return json.dumps(records, ensure_ascii=False)
    return "\n\n".join(records) or _LABELS["empty"]


def _render_entries(params: MemoryParams) -> list[str]:
    """按素材类型生成逐条记录。"""
    entries = params.entries
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
    return records


def _label_entries(params: MemoryParams, records: list[str]) -> list[str]:
    """按校验或蒸馏模式标注记录。"""
    if params.mode == "verify" or (
        params.mode in ("summarize", "summarize_task") and not params.verdicts
    ):
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
    return records
