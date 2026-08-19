"""trace 接口。

trace 是 replay / checkpoint / SSE 观测台 / 成本统计 / 失败聚合 / 实验归因的共同底座，
所以它的语义是**追加写的事件日志**，而不是"记录一下方便调试"。

接口按"能落盘、能重放、能推流"设计：
- `append` 不返回事件本身而是返回 event_id，因为落盘实现要在这里分配序号。
- `replay` 带 `after_event_id`，是给 SSE 断线重连补发用的（`Last-Event-ID`）。

**`run_id` 不在参数里**，由实现方在构造时持有：一次实验一个 trace 实例，
每条事件都属于它，让调用方一遍遍传是纯噪音，还给传错留了空间。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.core import EventType, Source, TraceEvent


@runtime_checkable
class TracePort(Protocol):
    """事件的追加与读取。**没有删除和修改**，这是刻意的。"""

    def append(
        self,
        episode_id: str,
        step: int,
        type: EventType,
        source: Source,
        payload: dict[str, str] | None = None,
    ) -> int:
        """追加一条事件，返回分配到的 event_id。

        前置条件：step >= 0。
        后置条件：返回的 event_id 严格大于此前任何一次 append 返回的值。
            实现方必须 assert 这条——SSE 的断线补发完全依赖它，
            一旦出现重复或回退，观测台会静默丢事件。

        `source` 是必填的：成本要按感知/决策拆开，失败要归到具体某一层。
        做成必填而不是可选，是因为可选参数最终总会有人不填。

        `ts` 与 `run_id` 由实现方填，调用方不传——它们是 trace 的属性，不是业务参数。
        """
        ...

    def replay(self, episode_id: str, after_event_id: int = -1) -> Iterable[TraceEvent]:
        """按 event_id 升序回放事件。

        前置条件：after_event_id >= -1（-1 表示从头开始）。
        后置条件：返回的事件 event_id 严格递增，且全部 > after_event_id。
        """
        ...
