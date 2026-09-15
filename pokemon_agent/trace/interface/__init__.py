"""trace/interface 包统一出口：`TracePort` 协议与形状协议。

- `Event` —— trace 眼里的"一条事件"（九属性，结构化满足即可）；
- `TracePort` —— 事件流的读写契约。

（`PersistedEvent` 已删，0913 晚：随 `project` 钩子一起下线——落盘记录就是
trace 自己的 `_Event`，不再有"项目侧另一种落盘形状"这回事。）

`TracePort` 的签名只收**裸字段**（`str` / `int` / `dict[str, str]` / `None`）
——这是 trace 被当作**独立模块**对待的那条边界：它不认识 `ModelCall` 之类的
业务类型，**也不认识自己的 `type` 值域**（那是声明方的事），"业务对象 → 裸
字段"的转换整个留给调用方的 tool 层（`tools/trace/render.py`）。

`TraceKind` **不在这里**（0913 定案）：它是 harness 的账目词表，消费者是
harness，搬去了 `pokemon_agent.schemas.harness`。`TraceEvent` 同样不在这里
（0913 下午）：它是跨层数据形状，搬去了 `pokemon_agent.schemas.harness.domain`。
`Source` 曾在同一处，已随"生产者维度下线"整个删除（0913 晚）。

**本包对 `pokemon_agent` 其余部分零 import**——`Event` 是纯协议、`TracePort`
签名里全是裸 `str`（0913 降级），所以这层没有一条出边。
"""

from __future__ import annotations

from .event import Event
from .trace_port import TracePort

__all__ = ["Event", "TracePort"]
