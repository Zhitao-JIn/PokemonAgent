"""`FromHarnessToMemoryToolQueryTaskMemoriesResp`：task 记忆检索响应。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.memory import TaskMemory


class FromHarnessToMemoryToolQueryTaskMemoriesResp(BaseModel):
    """**这一局的全部 task 记忆**，按 start_step 升序，不打分不截断。"""

    memories: list[TaskMemory] = Field(description="按 start_step 升序的 task 记忆")
