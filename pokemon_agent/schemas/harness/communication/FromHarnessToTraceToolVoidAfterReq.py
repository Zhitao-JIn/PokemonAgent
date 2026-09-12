"""`FromHarnessToTraceToolVoidAfterReq`：harness → `TraceTool` 的废弃打标请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToTraceToolVoidAfterReq(BaseModel):
    """把 trace 游标之后的事件作废（checkpoint 恢复的第二步）。

    调用方（`episode_entry.void_timeline`）已完成对账——`cursor` 来自恢复点那份
    存档的 `last_event_id`，`event_id > 它` 的事件全部属于废弃时间线。tool 不再
    自行校验，只按它打标。
    """

    cursor: int = Field(
        ge=-1, description="event_id > 它的全部事件原地打 valid=false；-1 = 一份都不留"
    )
