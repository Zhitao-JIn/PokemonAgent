"""`FromHarnessToMemoryToolStoreTaskMemoryReq`：harness → `MemoryTool` 的 task 记忆写入。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.memory import TaskMemory


class FromHarnessToMemoryToolStoreTaskMemoryReq(BaseModel):
    """落库一条**已经组装好**的 task 记忆（蒸馏在 `TaskSummarizer` 完成）。"""

    memory: TaskMemory = Field(description="组装好的 task 记忆")
