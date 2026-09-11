"""`FromHarnessToMemoryToolQueryEpisodeStepsResp`：
harness → `MemoryTool` 的整局单步记忆检索响应。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.memory import StepMemory


class FromHarnessToMemoryToolQueryEpisodeStepsResp(BaseModel):
    """**这一局的全部单步记忆**，按 step 升序，不打分不截断。"""

    steps: list[StepMemory] = Field(description="按 step 升序的单步记忆")
