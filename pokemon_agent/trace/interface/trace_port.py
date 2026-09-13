"""事件流接口：追加写的序列，按类型 mask 读。

原来放在顶层 `pokemon_agent/interfaces/trace/`；跟 `WorldPort` 搬到
`world/interface/` 是同一个道理——协议物理上挨着它自己的实现（`trace/store.py`
的 `LocalTrace`）走，`pokemon_agent/interfaces/` 这个集中注册表这次整个撤销，
消费方直接 `from pokemon_agent.trace import TracePort`。

**签名里的 `type`/`source` 是裸 `str`**（0913 降级）：trace 不可能只服务这一个
项目，它只保证"按时间记账"——**合法值域是声明方的事，trace 不认识它**。
调用方（harness/tool）用 `EventType.X`/`Source.Y` 这些字符串常量填，
但这些常量定义在声明方的模块里，本协议不 import。

**原 `cursor()` / `read_disk_events()` / `void_after()` 已删**：它们只服务
checkpoint 存档（游标）、恢复（主前缀回读）与废弃打标，随恢复链一起删掉了
（见 `CHANGELOG.md` 2026-09-13 第 57 条）。本协议现在只剩"追加写"一件能力。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class TracePort(Protocol):
    """事件的追加。"""

    def append(
        self,
        episode_id: str,
        step: int,
        type: str,
        source: str,
        payload: dict[str, str] | None = None,
        frame_png: str | None = None,
    ) -> int:
        """追加一条事件，返回分配到的 event_id。

        episode_id：所属 episode。
        step：发生在第几步。
        type：事件类型（字符串，取值由声明方定义）。
        source：由哪一层产生（字符串，取值由声明方定义）。
        payload：该类型的结构化内容。
        frame_png（关键字参数）：这一步
            感知到的原始画面（PNG 字节），直接存进这一条 `TraceEvent.frame_png`。
            由**感知的宿主**（`_begin` / `record_observation` / `perceive_after_action`）
            在写这条事件时调 `trace.append(..., frame_png=...)` 一并传入——
            `game_utils.perceive_with_retry()` 只把帧交回宿主，不再自己记账。多数事件
            没有对应的帧，留 `None`。**非 None 时实现方还应另存一份人眼可读的
            PNG 副本**（`LocalTrace` 存到这个 run 自己的
            `trace_data/<run_id>/screenshot/`，文件名 = 这条事件自己的
            `event_id`——截图与 trace 事件共享 id，永远递增零撞名）——
            `TraceEvent.frame_png` 仍是权威数据源，这份副本纯粹是方便肉眼翻看，
            丢了不影响任何回放/复现逻辑，因此不算进 `append()` 的后置条件。
        前置条件：step >= 0。
        后置条件：返回的 event_id 严格大于此前任何一次 append 的值（实现方 assert）；
            事件已落盘。
        """
        ...
