"""事件流接口：追加写的序列，按类型 mask 读。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pokemon_agent.schemas.datastore import EventType, Source


@runtime_checkable
class TracePort(Protocol):
    """事件的追加与读取。"""

    def cursor(self) -> int:
        """当前游标：最后一条已分配的 event_id（没有事件时 -1）。"""
        ...

    def append(
        self,
        episode_id: str,
        step: int,
        type: EventType,
        source: Source,
        payload: dict[str, str] | None = None,
        frame_png: str | None = None,
        screenshot_step: int | None = None,
    ) -> int:
        """追加一条事件，返回分配到的 event_id。

        episode_id：所属 episode。
        step：发生在第几步。
        type：事件类型。
        source：由哪一层产生。
        payload：该类型的结构化内容。
        frame_png（关键字参数）：这一步
            感知到的原始画面（PNG 字节），直接存进这一条 `TraceEvent.frame_png`。
            由 `episode_utils.perceive_with_retry()` 在给这次感知的 MODEL_CALL 调
            `trace.append(*args, frame_png=...)` 时一并传入。多数事件
            没有对应的帧，留 `None`。**非 None 时实现方还应另存一份人眼可读的
            PNG 副本**（`LocalTrace` 存到项目根目录 `screenshot/`，
            命名 `{run_id}_{episode_id}_{step}.png`，撞名加 `(n)` 后缀）——
            `TraceEvent.frame_png` 仍是权威数据源，这份副本纯粹是方便肉眼翻看，
            丢了不影响任何回放/复现逻辑，因此不算进 `append()` 的后置条件。
        screenshot_step：截图文件名单独用的 step 号，
            缺省等于 `step`——只有"这条事件记账用的 step"和"这张截图代表第几步
            的开局画面"数值不同时才需要传，见 `LocalTrace.append()` 的说明。
        前置条件：step >= 0。
        后置条件：返回的 event_id 严格大于此前任何一次 append 的值（实现方 assert）；
            事件已落盘。
        """
        ...

