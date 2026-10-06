"""task 层的观测（`TaskObservation`）：只读内存与屏幕缓冲、不调模型的那一档，多一个场合。

与 episode 层的 `Observation` 是两种观测。形状上沿用 `Observation` 的全部字段
（位置、状态行、`Facts`），再加 task 层自己的 `scene`，接管场合另带视图 `takeover`；
`perceived` 恒为假（这一档从不做视觉感知）。
"""

from __future__ import annotations

from pydantic import Field

from .observation import Observation
from .takeover_view import TakeoverView
from .task_scene import TaskScene


class TaskObservation(Observation):
    """**task 层的一帧**：RAM 档观测 + 场合。"""

    scene: TaskScene = Field(description="这一帧属于哪个场合（`world/scene.py::classify_scene`）")
    takeover: TakeoverView | None = Field(
        default=None, description="接管场合的视图；常规场合、或还没有接管脚本的接管场合为 None"
    )


__all__ = ["TaskObservation"]
