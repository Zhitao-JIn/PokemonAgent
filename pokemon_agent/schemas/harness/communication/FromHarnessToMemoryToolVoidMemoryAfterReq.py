"""`FromHarnessToMemoryToolVoidMemoryAfterReq`：harness → `MemoryTool` 的记忆截断请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToMemoryToolVoidMemoryAfterReq(BaseModel):
    """**把这一局 step 之后的记忆全部作废**（checkpoint 恢复）。"""

    episode_id: str = Field(description="这一局的标识")
    step: int = Field(ge=-1, description="保留 step ≤ 它的记录（含端点）；-1 = 整局废弃")
