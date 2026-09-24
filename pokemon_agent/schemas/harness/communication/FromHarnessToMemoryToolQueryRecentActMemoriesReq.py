"""`FromHarnessToMemoryToolQueryRecentActMemoriesReq`：
harness → `MemoryTool` 的近期按键记忆检索请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToMemoryToolQueryRecentActMemoriesReq(BaseModel):
    """**取这一局最近几条单步记忆**。"""

    episode_id: str = Field(description="这一局的标识")
    limit: int = Field(gt=0, description="条数上限")
