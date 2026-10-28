"""从相邻观察机械摘取带来源的事实。"""

from collections.abc import Sequence
from dataclasses import asdict

from pydantic import BaseModel

from .changes import FacingObject, Place, changes


class Fact(BaseModel):
    step: int
    kind: str
    place: Place | None = None
    object: FacingObject | None = None
    text: str
    task_id: str
    episode_id: str


def task_facts(entries: Sequence, task_id: str, episode_id: str) -> list[Fact]:
    """按原始顺序保留每次相邻观察的全部差异。"""
    result: list[Fact] = []
    for entry in entries:
        frames = [entry.before, *entry.observations, entry.after]
        for before, after in zip(frames, frames[1:], strict=False):
            for change in changes(before, after):
                result.append(Fact(**asdict(change), task_id=task_id, episode_id=episode_id))
    return result
