"""`FromHarnessToMemoryToolStoreEpisodeSummaryResp`：harness → `MemoryTool` 的跨局摘要写入响应。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.memory import EpisodeMemory


class FromHarnessToMemoryToolStoreEpisodeSummaryResp(BaseModel):
    """**落库后的那条摘要**（检索索引已同步更新）。"""

    memory: EpisodeMemory = Field(description="落库后的摘要记忆")
