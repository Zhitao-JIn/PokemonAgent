"""trace/interface 包统一出口：`TracePort` 协议 + `TraceKind` 记账词表。

`TraceKind` 是 trace 自己的词表（零依赖）；`TracePort` 的签名只收**裸字段**
（`str` / `int` / `dict[str, str]` / `None`）——这是 trace 被当作**独立模块**
对待的那条边界：它不认识 `ModelCall` 之类的业务类型，"业务对象 → 裸字段"的
转换整个留给调用方的 tool 层（`tools/trace/render.py`）。

两者都可以放心立即加载（不需要像 `world/interface` 里的 `WorldPort` 那样懒加载）：
本包只从 `..datastore` 拿自己的 `EventType`/`Source`，与 `pokemon_agent` 其余
部分**互不 import**。
"""

from __future__ import annotations

from .domain import TraceKind
from .trace_port import TracePort

__all__ = ["TraceKind", "TracePort"]
