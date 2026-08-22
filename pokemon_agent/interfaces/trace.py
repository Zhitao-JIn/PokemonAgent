"""trace 接口。

trace 是 replay / checkpoint / SSE 观测台 / 成本统计 / 失败聚合 / 实验归因的共同底座，
所以它的语义是**追加写的事件日志**，而不是"记录一下方便调试"。

接口按"能落盘、能重放、能推流"设计，三个方法各管一件事：

- `append` 持久化写入，**唯一的写入口**。不返回事件本身而是返回 event_id，
  因为落盘实现要在这里分配序号。
- `replay` 历史拉取，给 checkpoint/resume/离线重算用——读到调用发生的那一刻为止。
- `sse` 推流通道，给观测台用——**现在是打印到控制台，以后是推给浏览器的
  一条实时连接**，调用点不变，换的只是这个方法内部的实现。`append` 的实现
  必须在持久化之后调它一次：这样"发生了一条新事件"这件事只有一个源头，
  不需要在 `Harness` 或别处另开一条广播路径。

`append`/`replay` 是**拉**（调用方主动要），`sse` 是**推**（写入方主动送）——
三者的形状因此不同：前两者都带 `episode_id`/`after_event_id` 这类"我要哪一段"
的坐标，`sse` 只收一个已经写好的 `TraceEvent`，因为它不是在查，是在通知。

**`run_id` 不在参数里**，由实现方在构造时持有：一次实验一个 trace 实例，
每条事件都属于它，让调用方一遍遍传是纯噪音，还给传错留了空间。
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
        """
        ...

    def replay(self, episode_id: str, after_event_id: int = -1) -> Iterable[TraceEvent]:
        """按 event_id 升序回放事件。

        前置条件：after_event_id >= -1（-1 表示从头开始）。
        后置条件：返回的事件 event_id 严格递增，且全部 > after_event_id。
        """
        ...

    def sse(self, event: TraceEvent) -> None:
        """把一条刚写好的事件推给当前的观测通道。

        **不是查询，是通知**——只有 `append` 会调它，别处不该主动调。
        现在的实现是打印到控制台（`trace/store.py`）；以后换成推给浏览器的
        SSE 连接时，`append` 这一侧一行不用改，只有这个方法的实现会换。
        """
        ...
