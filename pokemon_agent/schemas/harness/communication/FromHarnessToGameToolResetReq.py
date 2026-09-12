"""`FromHarnessToGameToolResetReq`：harness → `GameTool` 的开局重置请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain.interface import Task


class FromHarnessToGameToolResetReq(BaseModel):
    """**这一局要打的任务**：重置到任务起点。"""

    task: Task = Field(description="本局任务")
