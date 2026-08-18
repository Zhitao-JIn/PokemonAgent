"""trace 接口。

trace 是 replay / checkpoint / SSE 观测台 / 成本统计四件事的共同底座（CLAUDE.md 铁律 5），
所以它的语义是**追加写的事件日志**，而不是"记录一下方便调试"。

本阶段只有 MockTrace 这个替身，但接口按"能落盘、能重放、能推流"设计：
- `append` 不返回事件本身而是返回 event_id，因为落盘实现要在这里分配序号。
- `replay` 带 `after_event_id`，是给 SSE 断线重连补发用的（`Last-Event-ID`）。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.core import EventType, TraceEvent


@runtime_checkable
class TracePort(Protocol):
    """事件的追加与读取。**没有删除和修改**，这是刻意的。"""

    def append(
        self,
        episode_id: str,
        step: int,
        type: EventType,
        payload: dict[str, str] | None = None,
    ) -> int:
        """追加一条事件，返回分配到的 event_id。

        前置条件：step >= 0。
        后置条件：返回的 event_id 严格大于此前任何一次 append 返回的值。
            实现方必须 assert 这条——SSE 的断线补发完全依赖它，
            一旦出现重复或回退，观测台会静默丢事件。
        注意 ts 由实现方填，调用方不传：时间戳是 trace 的属性，不是业务参数。
        """
        ...

    def replay(self, episode_id: str, after_event_id: int = -1) -> Iterable[TraceEvent]:
        """按 event_id 升序回放事件。

        前置条件：after_event_id >= -1（-1 表示从头开始）。
        后置条件：返回的事件 event_id 严格递增，且全部 > after_event_id。
        """
        ...
