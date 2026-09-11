"""`FromHarnessToMemoryToolQueryObjectEventsAtReq`：
harness → `MemoryTool` 的单格交互事件检索请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.world import PlaceInWorld


class FromHarnessToMemoryToolQueryObjectEventsAtReq(BaseModel):
    """**取这一格的交互事件**（判定层的 kind 兜底查询）。"""

    place: PlaceInWorld = Field(description="要查的物体格")
