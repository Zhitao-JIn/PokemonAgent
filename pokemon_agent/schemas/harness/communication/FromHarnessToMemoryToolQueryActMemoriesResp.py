"""`FromHarnessToMemoryToolQueryActMemoriesResp`：
harness → `MemoryTool` 的整局按键记忆检索响应。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.memory import ActMemory


class FromHarnessToMemoryToolQueryActMemoriesResp(BaseModel):
    """**这一局的全部按键记忆**，按 step 升序，不打分不截断。"""

    entries: list[ActMemory] = Field(description="按 step 升序的按键记忆")
