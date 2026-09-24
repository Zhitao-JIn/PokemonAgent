"""`FromHarnessToMemoryToolStoreActMemoryReq`：harness → `MemoryTool` 的单步记忆写入请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.memory import ActMemory


class FromHarnessToMemoryToolStoreActMemoryReq(BaseModel):
    """**要写入的一条单步记忆**。"""

    entry: ActMemory = Field(description="这一步的记忆")
