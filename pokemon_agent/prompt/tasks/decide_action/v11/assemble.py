"""decide_action v11：同构布局。"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from string import Template

from ...budget import render_budgets
from ...interfaces.assembly import Compose
from ...records import ActRecord, TaskRecord
from ..fragments.goal.params import GoalParams
from ..fragments.human_note.params import HumanNoteParams
from ..fragments.knowledge.params import KnowledgeParams
from ..fragments.memory_records.params import MemoryParams
from ..fragments.object_events.params import ObjectEventsParams
from ..fragments.prompt_layout.params import Block, PromptLayoutParams
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


def _actions(request: DecideActionParams, compose: Compose) -> str:
    """按原有顺序显示脚本和按键，不改变动作边界。"""
    space = request.space
    key_lines = [f"- {name}:" for name in space.names]
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
    action_sections: list[str] = []
    if navigation_lines:
        action_sections.append(_LABELS["L007"] + "\n".join(navigation_lines))
    if business_lines:
        action_sections.append(_LABELS["L008"] + "\n".join(business_lines))
    if key_lines:
        action_sections.append(_LABELS["L009"] + "\n".join(key_lines))
    return "\n\n".join(action_sections)


def _rules(params: DecideActionParams, compose: Compose) -> str:
    """固定按键读法与地图规则在本次输入之前。"""
    rules = _TEMPLATE.substitute(
        read_screen=compose("read_screen", ReadScreenParams()),
        repeat_hint=_PARTS["repeat_hint"],
    )
    rules += "\n\n" + _PARTS["button_help"] + "\n\n" + _map_guide(params, compose)
    if params.observation.covered_by_script:
        rules += "\n\n" + compose(
            "terrain_legend", TerrainLegendParams(meanings=params.terrain_meanings)
        )
    return rules


def _frame(params: DecideActionParams, compose: Compose) -> str:
    """当前现场包含按场合裁剪的观测、动作空间和上次脚本结果。"""
    frame = compose("task_frame", TaskFrameParams(observation=params.observation))
    frame += "\n\n可用动作：\n" + _actions(params, compose)
    if params.last_outcome is not None:
        outcome = params.last_outcome
        frame += _LABELS["outcome"].format(
            outcome.code, outcome.ok, outcome.summary, outcome.reason
        )
    if params.last_changes:
        frame += _LABELS["changes_header"]
        for change in params.last_changes:
            place = change.place
            location = f"{place.map_id}:{place.x}:{place.y}" if place else "-"
            obj = change.object.kind if change.object else "-"
            frame += _LABELS["change"].format(change.step, change.kind, location, obj, change.text)
    return frame


def assemble(params: DecideActionParams, compose: Compose) -> str:
    """v11：同构布局；动作与现场在输入区，按键与地图读法在规则区。"""
    assert params.space.names or params.space.entries, "build_prompt() got an empty action space"
    assert not params.observation.done, "build_prompt() called on a finished episode"
    assert params.goals, "build_prompt() got an empty goal stack"
    blocks: dict[Block, str] = {
        Block.RULES: _rules(params, compose),
        Block.GOAL: compose(
            "goal", GoalParams(entries=list(reversed(params.goals)), current_index=0)
        ),
        Block.KNOWLEDGE: compose("knowledge", KnowledgeParams(entries=[params.knowledge]))
        if params.knowledge
        else "",
        Block.INDEX: "\n".join(_memory_lines(params.task_index, "index", compose)),
        Block.OBJECTS: compose("object_events", ObjectEventsParams(events=params.known_objects))
        if (
            params.known_objects
            and params.observation.scene in {"walk", "shop"}
            and (params.observation.facts.overlay or "none") == "none"
        )
        else "",
        Block.HISTORY: "\n\n".join(_memory_lines(params.memories, "sequence", compose)),
        Block.FEEDBACK: "",
        Block.FRAME: _frame(params, compose),
        Block.BUDGET: render_budgets(params.budget_context) if params.budget_context else "",
        Block.HUMAN: compose("human_note", HumanNoteParams(note=params.human_note))
        if params.human_note.strip()
        else "",
    }
    return compose("prompt_layout", PromptLayoutParams(blocks=blocks))
