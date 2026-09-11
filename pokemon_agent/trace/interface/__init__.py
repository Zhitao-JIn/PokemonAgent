"""trace/interface 包统一出口：`TracePort` 协议 + `TraceKind` 账目词表。

两者都不依赖任何重实现（`TracePort` 只依赖 `schemas.trace` 的 `EventType`/
`Source`，`TraceKind` 零依赖），可以放心立即加载——不需要像 `world/interface`
里的 `WorldPort` 那样懒加载。

`schemas/trace/__init__.py` 因此保持它 docstring 里说的"依赖叶子，不引用任何
其他产出模块"——`TraceKind` 不再由它 re-export，需要的地方直接从这里拿。
"""

from __future__ import annotations

from .domain import TraceKind
from .trace_port import TracePort

__all__ = ["TraceKind", "TracePort"]
