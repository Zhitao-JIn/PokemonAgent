"""`FromHarnessToMemoryToolQueryObjectEventsReq`：harness → `MemoryTool` 的整图交互事件检索请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToMemoryToolQueryObjectEventsReq(BaseModel):
    """**取交互事件**——按元数据等值过滤。

    `map_id` 为 None = **不按地图筛**（0914 S2 放开）：这条读口原先只有"取这张地图
    上的事件"一种用法（局内检索有当前观测，知道自己在哪张图），但 run 级消费方
    （`plan`）要的是"本 run 涉及过的地图上都有什么"——它没有"当前地图"这个概念。
    让它先绕去 `step_memory` 的元数据里收集 `map_id` 再逐图查，是逼消费方自己拼索引。

    before_step 为 None = 不过滤；给值则只取严格早于它的事件（检索不读未来）。
    """

    map_id: int | None = Field(default=None, description="地图编号；None = 不按地图筛")
    before_step: int | None = Field(
        default=None, description="只取 step 严格小于它的事件；None = 不过滤"
    )
