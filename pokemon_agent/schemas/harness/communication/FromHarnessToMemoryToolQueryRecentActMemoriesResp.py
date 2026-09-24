"""`FromHarnessToMemoryToolQueryRecentActMemoriesResp`：
harness → `MemoryTool` 的近期按键记忆检索响应。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.memory import ActMemory


class FromHarnessToMemoryToolQueryRecentActMemoriesResp(BaseModel):
    """**最近几条按键记忆**，最新的在最后。"""

    steps: list[ActMemory] = Field(description="最新在最后的按键记忆")
