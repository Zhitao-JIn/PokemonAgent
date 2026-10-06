"""`agent_reviewer` 包统一出口：独立进程的视觉 LLM 复核席（`docs/agent_reviewer/spec.md`）。

由你本机起：`python -m pokemon_agent.agent_reviewer`（地址见 `.env` 的 `AGENT_REVIEWER_URL`）。
只依赖 `schemas` 与 `websockets`，不碰 harness / tools / brain / world / memory。
"""

from __future__ import annotations

from .agent import AgentReviewer

__all__ = ["AgentReviewer"]
