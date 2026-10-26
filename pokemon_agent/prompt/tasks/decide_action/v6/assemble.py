"""decide_action v6：仅调整布局，保留原料与规则。"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from string import Template

from ...interfaces.assembly import Compose
from ...records import ActRecord, GoalDefinition, TaskRecord
from ..fragments.human_note.params import HumanNoteParams
from ..fragments.memory_records.params import MemoryParams
from ..fragments.read_screen.params import ReadScreenParams
from ..fragments.script_signature.params import ScriptSignatureParams
from ..fragments.task_frame.params import TaskFrameParams
from ..fragments.terrain_legend.params import TerrainLegendParams
from .params import DecideActionParams

_PARTS = dict(
    re.findall(
        r"<!-- part:(\w+) -->\n(.*?)\n<!-- endpart -->",
        Path(__file__).with_name("prompt.md").read_text(encoding="utf-8"),
        re.S,
    )
)
_TEMPLATE = Template(_PARTS["main"])
_LABELS = json.loads(_PARTS["labels"])
_NAVIGATION_SCRIPTS = frozenset({"walk_to", "walk_to_adjacent", "face_direction", "exit_map"})


def _split(text: str, marker: str) -> dict[str, str]:
    """分段只修剪原先规则已经修剪的首尾空白。"""
    sections: dict[str, str] = {}
    name: str | None = None
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith(marker):
            if name is not None:
                sections[name] = "\n".join(lines).strip()
            name, lines = line.removeprefix(marker).strip(), []
        elif name is not None:
            lines.append(line)
    if name is not None:
        sections[name] = "\n".join(lines).strip()
    return sections


def _descriptions(request: DecideActionParams) -> dict[str, str]:
    """同一个键按本帧 overlay 选固定说明。"""
    sections = {
        name: _split(body, "### ") for name, body in _split(_PARTS["button_help"], "## ").items()
    }
    overlay = request.observation.facts.overlay or "none"
    return {
        name: sections[overlay].get(name, sections["none"].get(name, ""))
        for name in request.space.names
    }


def _map_guide(request: DecideActionParams, compose: Compose) -> str:
    """脚本接管隐藏地图规则；其他场合从符号表排版。"""
    if request.observation.covered_by_script:
        return ""
    return Template(_PARTS["map_hint"]).substitute(
        terrain_legend=compose(
            "terrain_legend", TerrainLegendParams(meanings=request.terrain_meanings)
        ),
        sample_map=_PARTS["sample_map"],
    )


def _memory_lines(
    entries: Sequence[ActRecord | TaskRecord], mode: str, compose: Compose
) -> list[str]:
    """保留逐条素材边界与相邻帧去重。"""
    return json.loads(
        compose("memory_records", MemoryParams(mode=mode, entries=list(entries), serialized=True))
    )


def _append_note(prompt: str, note: str, compose: Compose) -> str:
    """非空人类插话在模型请求最后组合。"""
    return prompt + compose("human_note", HumanNoteParams(note=note)) if note.strip() else prompt


def _render_goals(goals: list[GoalDefinition]) -> str:
    """消费原料并保留既有决策条件与排版。"""
    return "\n".join(
        (
            _LABELS["L001"].format(g.goal, _LABELS["L000"] if i == 0 else "", g.criteria)
            for i, g in enumerate(reversed(goals))
        )
    )


def assemble(params: DecideActionParams, compose: Compose) -> str:
    """消费原料并保留既有决策条件与排版。"""
    request = params
    goals, obs, space = (request.goals, request.observation, request.space)
    assert space.names or space.entries, "build_prompt() got an empty action space"
    assert not obs.done, "build_prompt() called on a finished episode"
    assert goals, "build_prompt() got an empty goal stack"
    facts = compose(
        "task_frame",
        TaskFrameParams(observation=request.observation, known_objects=request.known_objects),
    )
    recalled = "\n\n".join(_memory_lines(request.memories, "sequence", compose)) or _LABELS["L002"]
    key_lines = [
        _LABELS["L004"].format(name, _descriptions(request).get(name, _LABELS["L003"]))
        for name in space.names
    ]
    navigation_lines = [
        _LABELS["L005"].format(
            compose("script_signature", ScriptSignatureParams(entry=e)), e.description
        )
        for e in space.entries
        if e.kind == "script" and space.mask.get(e.name, False) and (e.name in _NAVIGATION_SCRIPTS)
    ]
    business_lines = [
        _LABELS["L006"].format(
            compose("script_signature", ScriptSignatureParams(entry=e)), e.description
        )
        for e in space.entries
        if e.kind == "script"
        and space.mask.get(e.name, False)
        and (e.name not in _NAVIGATION_SCRIPTS)
    ]
    action_sections = []
    if navigation_lines:
        action_sections.append(_LABELS["L007"] + "\n".join(navigation_lines))
    if business_lines:
        action_sections.append(_LABELS["L008"] + "\n".join(business_lines))
    if key_lines:
        action_sections.append(_LABELS["L009"] + "\n".join(key_lines))
    actions = "\n\n".join(action_sections)
    return _append_note(
        _TEMPLATE.substitute(
            goals=_render_goals(goals),
            status=_LABELS["L011"],
            facts=facts,
            map_guide=_map_guide(request, compose),
            knowledge=request.knowledge or _LABELS["L012"],
            memories=recalled,
            task_index="\n".join(
                _memory_lines([m], "index", compose)[0] for m in request.task_index
            )
            or _LABELS["L013"],
            actions=actions,
            repeat_hint=_PARTS["repeat_hint"],
            max_segments=request.max_segments,
            read_screen=compose("read_screen", ReadScreenParams()),
            last_result=_LABELS["L014"].format(request.last_result) if request.last_result else "",
        ),
        request.human_note,
        compose,
    )
