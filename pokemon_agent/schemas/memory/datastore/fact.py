"""事实摘要的跨层数据形状。"""

from __future__ import annotations

from pydantic import BaseModel

from .act_memory import SnapshotFacingObject as FacingObject
from .act_memory import SnapshotPlace as Place


class Fact(BaseModel):
    """由相邻观察机械摘取的一条带来源事实。"""

    step: int
    sub: int
    kind: str
    place: Place | None
    object: FacingObject | None
    text: str
    task_id: str
    episode_id: str


__all__ = ["Fact", "FacingObject", "Place"]
