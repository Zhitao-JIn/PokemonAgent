"""当前决策帧的版本化投影。"""

from __future__ import annotations

import json
from pathlib import Path

from ....interfaces.assembly import Compose
from ....observation import ObservationRecord
from ..memory_records.params import MemoryParams
from ..takeover.params import TakeoverParams
from .params import TaskFrameParams

_FRAME_FACT_KEYS = frozenset(
    {
        "where",
        "facing",
        "landmarks",
        "walk_map",
        "neighbors",
        "dialog_text",
        "screen",
        "options",
        "option_layout",
        "option_details",
        "cursor",
    }
)

_FRAME_FACT_KEYS = frozenset(
    {
        "where",
        "facing",
        "landmarks",
        "walk_map",
        "neighbors",
        "dialog_text",
        "screen",
        "options",
        "option_layout",
        "option_details",
        "cursor",
    }
)

_LABELS = json.loads(
    Path(__file__)
    .with_name("prompt.md")
    .read_text(encoding="utf-8")
    .split("<!-- labels -->\n", 1)[1]
)


def render_frame(observation: ObservationRecord, compose: Compose) -> str:
    """按场合投影原始字段，保留旧条件与排版。"""
    header = _LABELS["L000"].format(str(observation.covered_by_script).lower())
    if observation.covered_by_script:
        body = (
            compose("takeover", TakeoverParams(view=observation.takeover))
            if observation.takeover is not None
            else _compact_screen(observation.facts.screen) or _LABELS["L001"]
        )
        body += _LABELS["L002"].format(observation.facts.overlay or "none")
        if observation.facts.cursor:
            body += _LABELS["L003"].format(observation.facts.cursor)
        screen = _compact_screen(observation.facts.screen)
        if observation.takeover is not None and screen:
            body += _LABELS["L004"].format(screen)
        if observation.selected_map_location is not None:
            body += _LABELS["L005"].format(observation.selected_map_location)
            if json.loads(
                compose(
                    "memory_records",
                    MemoryParams(mode="facts", entries=[], observation=observation),
                )
            ).get("where", ""):
                body += _LABELS["L006"].format(
                    json.loads(
                        compose(
                            "memory_records",
                            MemoryParams(mode="facts", entries=[], observation=observation),
                        )
                    ).get("where", "")
                )
        return _with_notes(_LABELS["L007"].format(header, body), observation)
    facts = json.loads(
        compose("memory_records", MemoryParams(mode="facts", entries=[], observation=observation))
    )
    facts = {
        key: value
        for key, value in facts.items()
        if key in _FRAME_FACT_KEYS or key.startswith(("my_", "foe_"))
    }
    fields = _visible_fields(observation, facts)
    lines = [_LABELS["L008"].format(observation.scene), header]
    lines.append(_LABELS["L009"].format(observation.facts.overlay or "none"))
    visible = [(key, value) for key, value in fields if value]
    lines.extend((_LABELS["L010"].format(key, value) for key, value in visible))
    return _with_notes("\n".join(lines), observation)


def _with_notes(body: str, observation: ObservationRecord) -> str:
    """按场合投影原始字段，保留旧条件与排版。"""
    if observation.menu_decode_complete is not None and (
        observation.facts.overlay == "choice" or observation.menu_decode_complete is False
    ):
        body += _LABELS["L011"].format(str(observation.menu_decode_complete).lower())
    notes = _notes(observation)
    if observation.scene in {"walk", "shop"} and observation.facts.overlay == "none":
        notes = [note for note in notes if not note.startswith(_LABELS["L012"])]
    if notes:
        body += "\n- observation_notes: " + _LABELS["L013"].join(notes)
    return body


def _visible_fields(observation: ObservationRecord, facts: dict[str, str]) -> list[tuple[str, str]]:
    """按场合投影原始字段，保留旧条件与排版。"""
    overlay = observation.facts.overlay or "none"
    if observation.scene in {"walk", "shop"} and overlay == "none":
        keys = ["where", "facing", "landmarks"]
        keys.append("walk_map" if facts.get("walk_map") else "neighbors")
        fields = [(key, facts.get(key, "")) for key in keys]
    elif overlay == "dialog" and observation.scene not in {"pokemon_info", "start_menu", "title"}:
        fields = []
        if observation.scene in {"dialog", "shop"}:
            fields.append(("where", facts.get("where", "")))
        fields.append(("dialog_text", facts.get("dialog_text", "")))
        if not facts.get("dialog_text"):
            fields.append(("screen", _compact_screen(observation.facts.screen)))
    elif observation.facts.screen:
        fields = [("screen", _compact_screen(observation.facts.screen))]
    else:
        keys = ["dialog_text", "option_layout", "option_details"]
        if not facts.get("option_layout"):
            keys.extend(["options", "cursor"])
        fields = [(key, facts.get(key, "")) for key in keys]
    if observation.scene in {"dialog", "shop"} and (
        overlay != "none" and (not any((key == "where" for key, _ in fields)))
    ):
        fields.insert(0, ("where", facts.get("where", "")))
    if observation.scene == "battle":
        fields.extend(
            ((key, value) for key, value in facts.items() if key.startswith(("my_", "foe_")))
        )
    return fields


def _compact_screen(screen: str) -> str:
    """按场合投影原始字段，保留旧条件与排版。"""
    return "\n".join(line.rstrip() for line in screen.splitlines() if line.strip())


def _notes(observation: ObservationRecord) -> list[str]:
    """从结构化限制标志生成措辞；旧观测缺标志时由同帧原料推导。"""
    notes: list[str] = []
    flags = set(observation.observation_flags)
    if "observation_flags" not in observation.model_fields_set:
        if not (
            observation.facts.screen or observation.facts.dialog_text or observation.facts.options
        ):
            flags.add("no_text")
        if observation.menu_decode_complete is False:
            flags.add("incomplete_menu")
        if observation.covered_by_script and observation.takeover is None:
            flags.add("missing_takeover")
        if observation.scene == "transition":
            flags.add("transition")
    if "no_text" in flags:
        notes.append(_LABELS["L015"])
    if "incomplete_menu" in flags:
        if observation.covered_by_script:
            notes.append(_LABELS["L016"])
        else:
            notes.append(_LABELS["L017"])
    if "missing_takeover" in flags:
        notes.append(_LABELS["L018"])
    if "transition" in flags:
        notes.append(_LABELS["L019"])
    return notes


def assemble(params: TaskFrameParams, compose: Compose) -> str:
    """返回当前操作所需的可见事实。"""
    return render_frame(params.observation, compose)
