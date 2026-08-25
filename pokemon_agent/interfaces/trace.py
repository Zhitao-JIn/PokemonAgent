"""事件流的接口：**追加写的序列**，不是可变的状态快照。

trace 是 replay、checkpoint、SSE 观测台、成本统计四件事的共同底座，所以它只有
一个写入动作（`append`）和两个读出动作（`replay` / `sse`），没有"改一条"或"删一条"。

`event_id` **严格单调递增**，这是全文件最硬的一条：SSE 断线重连靠它补发，
一旦重号或回退，观测台会静默丢事件——静默是最坏的一种坏。实现方必须 assert 它。

本阶段只有内存实现，但接口按"能落盘"设计：`append` 的参数是五个标量加一个
`dict[str, str]`，没有活对象，序列化不需要额外一层转换。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.trace import EventType, Source, TraceEvent


@runtime_checkable
class TracePort(Protocol):
    """事件的追加、读取与推送。**没有删除和修改**，这是刻意的。"""

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
            **实现方必须在持久化之后调一次 `self.sse(event)`**——推流的事件
            和落盘的事件是同一条，不能有第二个源头。

        `source` 是必填的：成本要按感知/决策拆开，失败要归到具体某一层。
        做成必填而不是可选，是因为可选参数最终总会有人不填。

        `ts` 与 `run_id` 由实现方填，调用方不传——它们是 trace 的属性，不是业务参数。

        把一条事件追加进流里，返回它拿到的 event_id。
        """
        ...

    def replay(self, episode_id: str, after_event_id: int = -1) -> Iterable[TraceEvent]:
        """按 event_id 升序回放事件。

        前置条件：after_event_id >= -1（-1 表示从头开始）。
        后置条件：返回的事件 event_id 严格递增，且全部 > after_event_id。

        按 event_id 升序把事件读回来。
        """
        ...

    def sse(self, event: TraceEvent) -> None:
        """把一条刚写好的事件推给当前的观测通道。

        **不是查询，是通知**——只有 `append` 会调它，别处不该主动调。
        现在的实现是打印到控制台（`trace/store.py`）；以后换成推给浏览器的
        SSE 连接时，`append` 这一侧一行不用改，只有这个方法的实现会换。

        把刚写好的这条事件推给当前的观测通道。
        """
        ...
