"""`FromHarnessToGameToolPerceiveTaskResp`：harness → `GameTool` 的 task 层感知响应。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.world import RamReadout, TaskObservation


class FromHarnessToGameToolPerceiveTaskResp(BaseModel):
    """**task 层一帧的全部产物**：观测（带场合）+ 原始帧 + 内存读数。

    字段摊平自 world 的 `TaskPerceived`；这一档不调模型，没有模型调用记录。
    """

    observation: TaskObservation = Field(description="这一帧的观测（带场合）")
    frame_png: str = Field(description="这一帧的原始画面（PNG data URI）")
    ram: RamReadout | None = Field(
        default=None, description="本帧内存读数，先落 trace；run 判定可按最近五次窗口读取"
    )
