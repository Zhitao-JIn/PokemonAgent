"""Derive NPC conversations from the observation sequence in action-memory writes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from pokemon_agent.memory.changes import changes

from .stream import RunStream


class _Observation(BaseModel):
    """Keep the trace snapshot shape while validating its required step coordinate."""

    model_config = ConfigDict(extra="allow")

    step: int


def interacted_npcs(stream: RunStream, episode_ids: list[str]) -> dict[tuple[int, int, int], str]:
    """Return NPC coordinates with a newly observed dialog line and its act-memory event UUID."""
    interacted: dict[tuple[int, int, int], str] = {}
    for event in stream.in_episodes(episode_ids, "write_act_memory"):
        content = event.content.model_dump(mode="python")
        raw_frames: list[Any] = [
            content["before"],
            *content.get("observations", []),
            content["after"],
        ]
        frames = [_Observation.model_validate(frame) for frame in raw_frames]
        for before, after in zip(frames, frames[1:], strict=False):
            for change in changes(before, after):
                obj = change.object
                if change.kind != "dialog_line" or obj is None or obj.kind != "人":
                    continue
                place = obj.place
                interacted[(place.map_id, place.x, place.y)] = event.uuid
    return interacted


__all__ = ["interacted_npcs"]
