"""事件流接口：追加写的序列 + 按局读。

协议物理上挨着它自己的实现（`trace/store.py` 的 `LocalTrace`）走，消费方直接
`from pokemon_agent.trace import TracePort`。

**签名里的 `type` / `kind` 是裸 `str`**（0913 降级）：trace 不可能只服务这一个
项目，它只保证"按时间记账"——**合法值域是声明方的事，trace 不认识它**。调用方
（tool 层）用 `EventType.X` / `TraceKind.X` 这些值填。

**`meta` / `content` 是"不透明载荷"**：trace 只把它们序列化成 JSON 字符串落盘、
读回时原样交还，**不解释里面装了什么**。`meta` 里有什么键由 harness 定
（`source` / `episode_id` / `step`），本类只额外盖一个 `run_id`（run 目录名，
它自己知道）。

**已删的两件**（0914 封套改造）：`read_event(event_id)`——它是"按 id 取单条"的
唯一入口，而那个能力随 `frame_png` 一起下线（画面真源搬到
`memory/step_memory/`）。此前的 `cursor()` / `read_disk_events()` / `void_after()`
随 checkpoint 恢复链删掉（0913 第 57 条）；`read_screenshot` 随截图副本删掉。

**读能力只剩一条通用读方法**：`read_events` ——不做掩码、不做游标、不打标，
只回答"盘上有什么"。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .event import Event


@runtime_checkable
class TracePort(Protocol):
    """事件的追加写 + 按需读。"""

    def append(
        self,
        type: str,
        kind: str,
        meta: dict[str, Any] | None = None,
        content: Any = None,  # noqa: ANN401 —— 账的本体就是任意可 JSON 化的对象
    ) -> str:
        """追加一条事件，返回它的 `uuid`（= 文件名）。

        type：事件种类（字符串，取值由声明方定义）。
        kind：账名（字符串，取值由声明方定义）。
        meta：harness 自报的签名信息（`source` / `episode_id` / `step`…）。
            **实现方会往它里面盖一个 `run_id`**——那是 run 目录名，
            落盘那一层自己知道（见 `store._stamp_run_id`）。调用方不要自己带
            `run_id` 键。
        content：这笔账的本体，任何可 JSON 化的对象。

        `meta` / `content` 在盘上是 **JSON 字符串**（需要一层转义），
        序列化由实现方做一处，读端 `json.loads` 回来。

        前置条件：`meta` 不带 `run_id` 键。
        后置条件：六个字段（`uuid`/`kind`/`type`/`ts`/`meta`/`content`）已全部
            落盘；返回的 uuid 与文件名同值。
        """
        ...

    def read_events(self, episode_id: str | None = None) -> list[Event]:
        """读已落盘的全部事件，按 `(ts, uuid)` 升序；可按局切片。

        episode_id：`None` = 不过滤，返回这个 run 的全部事件；给了就只返回
            `meta.episode_id` 与它相等的那批。
        后置条件：按 `(ts, uuid)` 严格升序；无匹配时返回空列表（不抛异常）。
        失败：磁盘读取失败原样抛出（权限/IO）——本方法不吞这一类错。
        """
        ...
