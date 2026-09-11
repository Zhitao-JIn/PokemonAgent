"""trace/datastore 包：落盘的事件记录形状 + 它的枚举、版本号。

原来放在 `pokemon_agent/schemas/trace/datastore/`——这几个类是 trace 包自己
落盘的记录形状，不是"给别的模块看的信封"，物理上归回 `trace/` 自己，
`schemas/` 不再保留 `trace` 子包。

只做 re-export、不定义新实体，消费方写 `from pokemon_agent.trace import X`
（顶层 `trace/__init__.py` 会再转一手）。
"""

__all__ = ["TRACE_SCHEMA_VERSION", "EventType", "Source", "TraceEvent"]
from .trace_event import TRACE_SCHEMA_VERSION, EventType, Source, TraceEvent
