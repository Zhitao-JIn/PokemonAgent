"""只能从 episode 起点开始的 trace replay 读取器。"""

from __future__ import annotations

from collections.abc import Iterable

from pokemon_agent.schemas.trace import EventType, TraceEvent


class EpisodeReplay:
    """验证并按原始顺序读取一整个 episode，不支持从中间续播。"""

    def __init__(self, events: Iterable[TraceEvent]) -> None:
        self._events = sorted(events, key=lambda event: event.event_id)

    def play(self) -> list[TraceEvent]:
        """从头返回事件；缺少边界事件或顺序错误时拒绝 replay。"""
        assert self._events, "cannot replay an empty episode"
        assert self._events[0].type is EventType.EPISODE_START, "replay must start at episode boundary"
        assert self._events[-1].type is EventType.EPISODE_END, "replay requires a completed episode"
        assert all(
            left.event_id < right.event_id
            for left, right in zip(self._events, self._events[1:])
        ), "event ids must be strictly increasing"
        return list(self._events)
