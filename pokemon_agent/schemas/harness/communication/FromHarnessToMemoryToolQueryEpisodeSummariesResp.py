"""`FromHarnessToMemoryToolQueryEpisodeSummariesResp`：
harness → `MemoryTool` 的跨局摘要检索响应。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.memory import EpisodeMemory


class FromHarnessToMemoryToolQueryEpisodeSummariesResp(BaseModel):
    """**命中的跨局摘要**，按场景匹配 + 相关性 + 质量排序。"""

    summaries: list[EpisodeMemory] = Field(description="排序后的跨局摘要")
