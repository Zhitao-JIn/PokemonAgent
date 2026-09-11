"""`FromHarnessToMemoryToolAppendObjectEventsReq`：harness → `MemoryTool` 的交互事件追加请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.memory import ObjectFactEvent


class FromHarnessToMemoryToolAppendObjectEventsReq(BaseModel):
    """**一批要追加的交互事件**（写穿：落盘与索引同时生效）。"""

    events: list[ObjectFactEvent] = Field(description="判定层构造好的事件")
