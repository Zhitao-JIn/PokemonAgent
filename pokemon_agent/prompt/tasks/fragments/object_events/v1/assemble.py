"""注册片段 v1：固定文本与原料排版。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from ....interfaces.assembly import Compose
from ....objects import ObjectDialogEvent, ObjectFactEvent, ObjectStillEvent, ObjectWarpEvent
from .params import ObjectEventsParams

_LABELS = json.loads(
    Path(__file__)
    .with_name("prompt.md")
    .read_text(encoding="utf-8")
    .split("<!-- labels -->\n", 1)[1]
)


def render_object_events(events: Sequence[ObjectFactEvent]) -> str:
    """按原条件和顺序渲染独立原料。"""
    ordered = sorted(events, key=lambda e: e.step)
    return "\n".join(_render_line(e) for e in ordered)


def _render_line(event: ObjectFactEvent) -> str:
    """按原条件和顺序渲染独立原料。"""
    if isinstance(event, ObjectDialogEvent):
        outcome = _LABELS["L000"].format(event.text)
    elif isinstance(event, ObjectWarpEvent):
        outcome = _LABELS["L001"].format(event.map_id)
    elif isinstance(event, ObjectStillEvent):
        outcome = _LABELS["L002"]
    else:
        outcome = str(event)
    actor = event.actor_place
    cell = event.place
    return _LABELS["L003"].format(
        event.episode_id,
        event.step,
        actor.x,
        actor.y,
        event.button,
        cell.map_id,
        cell.x,
        cell.y,
        event.object_kind,
        outcome,
    )


def assemble(params: ObjectEventsParams, compose: Compose) -> str:
    """按步号稳定排序后逐事件一行。"""
    return render_object_events(params.events)
