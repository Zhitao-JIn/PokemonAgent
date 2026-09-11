"""`FromHarnessToMemoryToolQueryRecentStepsReq`：harness → `MemoryTool` 的近期单步记忆检索请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToMemoryToolQueryRecentStepsReq(BaseModel):
    """**取这一局最近几条单步记忆**。"""

    episode_id: str = Field(description="这一局的标识")
    limit: int = Field(gt=0, description="条数上限")
