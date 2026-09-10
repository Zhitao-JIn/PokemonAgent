"""`FromHarnessToGameToolSetTaskReq`：harness → `GameTool` 的任务改挂请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.brain import TaskForBrain


class FromHarnessToGameToolSetTaskReq(BaseModel):
    """**不重置世界、只把任务换掉**（checkpoint 恢复后补挂任务用）。"""

    task: TaskForBrain = Field(description="要挂上的任务")
