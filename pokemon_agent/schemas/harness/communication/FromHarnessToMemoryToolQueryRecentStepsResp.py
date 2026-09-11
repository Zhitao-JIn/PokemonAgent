"""`FromHarnessToMemoryToolQueryRecentStepsResp`：harness → `MemoryTool` 的近期单步记忆检索响应。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.memory import StepMemory


class FromHarnessToMemoryToolQueryRecentStepsResp(BaseModel):
    """**最近几条单步记忆**，最新的在最后。"""

    steps: list[StepMemory] = Field(description="最新在最后的单步记忆")
