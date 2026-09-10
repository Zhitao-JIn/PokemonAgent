"""harness → trace tool 的 read_disk_events 交互：读盘请求。"""

from __future__ import annotations

from pydantic import BaseModel


class FromHarnessToTraceToolReadDiskEventsReq(BaseModel):
    """读盘上全部事件（checkpoint 恢复对账用）。

    当前无参数——落盘路径由 trace tool 自己持有；留空信封占位，
    后续若要按 run/episode 过滤在此扩字段。
    """
