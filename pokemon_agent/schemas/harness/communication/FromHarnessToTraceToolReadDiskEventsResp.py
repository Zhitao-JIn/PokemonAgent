"""harness → trace tool 的 read_disk_events 交互：读盘响应。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.trace import TraceEvent


class FromHarnessToTraceToolReadDiskEventsResp(BaseModel):
    """盘上全部事件，按 `event_id` 升序（TracePort 落盘顺序即写入顺序）。"""

    events: list[TraceEvent] = Field(description="全部事件，按 event_id 升序")
