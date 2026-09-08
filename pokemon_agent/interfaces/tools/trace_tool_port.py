"""`TraceToolPort`：harness 直接持有的、跟事件流沟通的门面。

两个方法，跟 `TracePort` 一一对应：
- `append`：harness 只组装 `FromHarnessToTraceToolAppendReq`（挑字段 + 声明
  kind），payload 字段格式、条件字段、一拆多全部是 tool 的处理；
- `events`：读侧没有要转换的数据，原样转发（调用方拿存储形状 `TraceEvent`）。

**边界不对称**：写者只有 harness（走本端口）；读者是 api/evaluation
（运维侧，直读 `TracePort`/`LocalTrace`，不进 tool 层）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.communication import FromHarnessToTraceToolAppendReq
from pokemon_agent.schemas.datastore import TraceEvent


@runtime_checkable
class TraceToolPort(Protocol):
    """事件流的记账与读取。"""

    def append(self, req: FromHarnessToTraceToolAppendReq) -> int:
        """记一笔账，返回最后一条事件分到的 event_id。

        前置条件：req.kind 对应渲染所需字段非空（tool 入口 assert）。
        后置条件：渲染出的全部事件已落盘；返回的 event_id 严格大于此前
            任何一次 append 的值（一次 req 可能展开成多条事件，如
            `model_call` 的账单 + 失败补 ERROR）。
        """
        ...

    def cursor(self) -> int:
        """当前游标：最后一条已分配的 event_id（checkpoint 快照用）。"""
        ...

    def read_disk_events(self) -> list[TraceEvent]:
        """读盘上全部事件（checkpoint 恢复的主前缀来源，event_id 升序）。"""
        ...
