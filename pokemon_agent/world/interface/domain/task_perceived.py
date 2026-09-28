"""`TaskPerceived`：world 给 task 层的一次感知——只读内存与屏幕缓冲，不调模型，所以没有账。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .ram_readout import RamReadout
from .task_observation import TaskObservation


class TaskPerceived(BaseModel):
    """**task 层的一帧**：观测（带场合）+ 原始帧 + 内存读数。

    与 episode 层的 `Perceived` 是两种产物：这一档从不问视觉模型，没有模型调用记录，也不会失败。
    """

    observation: TaskObservation = Field(description="这一帧的观测（带场合）")
    frame_png: str = Field(description="这一帧的原始画面（PNG data URI）")
    ram: RamReadout | None = Field(
        default=None, description="这一帧的内存读数，只进 trace（`sense_frame.content.ram`）"
    )


__all__ = ["TaskPerceived"]
