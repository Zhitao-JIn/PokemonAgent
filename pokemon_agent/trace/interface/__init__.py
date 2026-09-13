"""trace/interface 包统一出口：`TracePort` 协议。

`TracePort` 的签名只收**裸字段**（`str` / `int` / `dict[str, str]` / `None`）
——这是 trace 被当作**独立模块**对待的那条边界：它不认识 `ModelCall` 之类的
业务类型，**也不认识自己的 `type`/`source` 值域**（那是声明方的事），
"业务对象 → 裸字段"的转换整个留给调用方的 tool 层（`tools/trace/render.py`）。

`TraceKind` **不在这里**（0913 定案）：它是 harness 的账目词表，消费者是
harness，搬去了 `pokemon_agent.schemas.harness`。本包只剩协议。

**`TracePort` 对 `pokemon_agent` 其余部分零 import**——它连自己的
`Type`/`Source` 值域都不引，签名里就是裸 `str`（0913 降级）。这是 trace
被当作**独立模块**对待的那条边界。
"""

from __future__ import annotations

from .trace_port import TracePort

__all__ = ["TracePort"]
