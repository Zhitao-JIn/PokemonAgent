"""`FromHarnessToMemoryToolStoreEpisodeSummaryReq`：harness → `MemoryTool` 的跨局摘要写入请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.memory import EpisodeMemory


class FromHarnessToMemoryToolStoreEpisodeSummaryReq(BaseModel):
    """**已经组装好的跨局摘要**：这一层只落盘、不调模型。"""

    memory: EpisodeMemory = Field(description="组装好的摘要记忆")
