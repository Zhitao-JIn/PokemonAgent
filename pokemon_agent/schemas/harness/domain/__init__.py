"""`schemas/harness/domain` 包统一出口：`TraceKind`。

只做 re-export、不定义任何实体。
"""

from __future__ import annotations

from .trace_kind import TraceKind

__all__ = ["TraceKind"]
