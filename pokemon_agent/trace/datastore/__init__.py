"""trace/datastore 包：trace 落盘记录的**词表**。

原来放在 `pokemon_agent/schemas/trace/datastore/`——这些是 trace 包自己落盘的
记录形状，不是"给别的模块看的信封"，物理上归回 `trace/` 自己，
`schemas/` 不再保留 `trace` 子包。

**本包只剩一件**：

- `EventType` / `EventTypeName` —— 这条记录的**粗类**词表（7 个值）；
  `store.py` 真的读它（判"这一段收尾了吗"）。

搬走/删掉的：`TraceEvent` → `schemas/harness/domain/`（跨层数据形状）；
`Source`（0913 晚整个删除：生产者维度下线）；`TRACE_SCHEMA_VERSION`
（0914 删除：恒 `5`、零读方、两份副本要人工同步）。
`_Event`（trace 私有的具体实现）住在 `event.py`，**不进这里的 `__all__`**
——外部一律通过 `trace.interface.Event` 协议说话，它只服务 `trace/store.py`。

只做 re-export、不定义新实体，消费方写 `from pokemon_agent.trace import X`
（顶层 `trace/__init__.py` 会再转一手）。
"""

__all__ = ["EventType"]
from .trace_event import EventType
