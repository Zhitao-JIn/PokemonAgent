"""记账层产出的契约：落盘的事件记录形状与它的枚举、版本号。本包是依赖叶子，
不引用任何其他产出模块。

`TraceKind`（账目种类）原来也在这里，现在归 `trace/` 自己（`trace/interface/`），
不再是"给别人看的数据契约"，而是这个模块自己的账目词表——`from
pokemon_agent.trace import TraceKind`。

本文件是 `schemas/trace/` 的统一出口，只做 re-export、不定义任何实体；
消费方只写 `from pokemon_agent.schemas.trace import X`，不深到 communication/ 等子目录。
"""

__all__ = [
    "EventType",
    "Source",
    "TRACE_SCHEMA_VERSION",
    "TraceEvent",
]
from .datastore.trace_event import TRACE_SCHEMA_VERSION, EventType, Source, TraceEvent
