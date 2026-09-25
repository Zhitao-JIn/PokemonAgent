"""`review_backend` 包统一出口：人在环的常驻后端（`docs/web_reviewer/spec.md` §5–6）。

独立进程，由你本机起：`python -m pokemon_agent.review_backend [--port N]`。
只依赖 `schemas` 与 `websockets`，不碰 harness / tools / brain / world / memory。

只做 re-export、不定义任何实体。
"""

from __future__ import annotations

from .backend import HISTORY_LIMIT, ReviewBackend

__all__ = ["HISTORY_LIMIT", "ReviewBackend"]
