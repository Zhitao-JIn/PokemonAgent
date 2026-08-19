"""MockTrace —— TracePort 的替身实现，把事件堆在内存列表里。

**它是 mock。** 它确实满足 TracePort 的契约（event_id 单调、replay 能按 episode 过滤），
但真正的 trace 要落盘、要能推流给 SSE 观测台、要作为 checkpoint 的事件源、
要能按失败类型聚合统计——这些一个都没有。它存在只是为了让大脑这一层能跑起来。

保留它满足契约这一点是有意的：替身也必须遵守契约，否则换成真实实现时上层会崩。
"""

from __future__ import annotations

import time
from collections.abc import Iterable

from pokemon_agent.schemas.core import EventType, Source, TraceEvent


class MockTrace:
    """事件的追加与回放。没有删除和修改，这是刻意的。"""

    def __init__(self, run_id: str = "local") -> None:
        """`run_id` 在构造时定：一次实验一个 trace 实例，每条事件都属于它。"""
        self._run_id = run_id
        self._events: list[TraceEvent] = []
        self._next_id = 0

    def append(
        self,
        episode_id: str,
        step: int,
        type: EventType,
        source: Source,
        payload: dict[str, str] | None = None,
    ) -> int:
        """追加一条事件，返回分配到的 event_id。

        前置条件：step >= 0、episode_id 非空。
        后置条件：返回值严格大于此前任何一次 append 的返回值。
            SSE 的断线补发完全依赖这条，一旦重复或回退，观测台会静默丢事件。
        """
        assert step >= 0, f"step must be >= 0, got {step}"
        assert episode_id, "append() got an empty episode_id"

        event_id = self._next_id
        self._next_id += 1

        self._events.append(
            TraceEvent(
                event_id=event_id,
                run_id=self._run_id,
                episode_id=episode_id,
                step=step,
                type=type,
                source=source,
                payload=payload or {},
                # ts 由实现方填：时间戳是 trace 的属性，不是业务参数。
                ts=time.time(),
            )
        )

        assert not self._events[:-1] or event_id > self._events[-2].event_id, (
            "event_id must be strictly increasing"
        )
        return event_id

    def replay(self, episode_id: str, after_event_id: int = -1) -> Iterable[TraceEvent]:
        """按 event_id 升序回放某个 episode 的事件。

        前置条件：after_event_id >= -1（-1 表示从头开始）。
        后置条件：返回的事件 event_id 严格递增且全部 > after_event_id。
        """
        assert after_event_id >= -1, f"after_event_id must be >= -1, got {after_event_id}"

        # 内部 list 本身就是按 event_id 升序追加的，不需要再排序。
        return [
            e
            for e in self._events
            if e.episode_id == episode_id and e.event_id > after_event_id
        ]

    # ---- 便于测试与调试，不属于 TracePort 契约 ----

    def all_events(self) -> list[TraceEvent]:
        """全部事件（含所有 episode）。测试断言用。"""
        return list(self._events)

    def count(self, episode_id: str, type: EventType) -> int:
        """某个 episode 里某类事件的条数。测试断言重试次数、失败次数用。"""
        return sum(1 for e in self._events if e.episode_id == episode_id and e.type is type)
