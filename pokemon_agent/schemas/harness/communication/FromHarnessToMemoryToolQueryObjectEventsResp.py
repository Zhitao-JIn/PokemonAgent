"""`FromHarnessToMemoryToolQueryObjectEventsResp`：
harness → `MemoryTool` 的整图交互事件检索响应。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.memory import ObjectFactEvent


class FromHarnessToMemoryToolQueryObjectEventsResp(BaseModel):
    """**这张地图上的交互事件**，按 step 升序；无记录时为空列表。"""

    events: list[ObjectFactEvent] = Field(description="按 step 升序的交互事件")
