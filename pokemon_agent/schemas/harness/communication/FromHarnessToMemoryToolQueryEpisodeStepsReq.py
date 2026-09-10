"""`FromHarnessToMemoryToolQueryEpisodeStepsReq`：harness → `MemoryTool` 的整局单步记忆检索请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToMemoryToolQueryEpisodeStepsReq(BaseModel):
    """**取这一局的全部单步记忆**。"""

    episode_id: str = Field(description="这一局的标识")
