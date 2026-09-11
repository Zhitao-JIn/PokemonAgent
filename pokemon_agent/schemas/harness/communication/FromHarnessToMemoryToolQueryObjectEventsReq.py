"""`FromHarnessToMemoryToolQueryObjectEventsReq`：harness → `MemoryTool` 的整图交互事件检索请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToMemoryToolQueryObjectEventsReq(BaseModel):
    """**取这张地图上的交互事件**。

    before_step 为 None = 不过滤；给值则只取严格早于它的事件（检索不读未来）。
    """

    map_id: int = Field(description="地图编号")
    before_step: int | None = Field(
        default=None, description="只取 step 严格小于它的事件；None = 不过滤"
    )
