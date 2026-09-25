"""`FromHarnessToMemoryToolQueryActMemoriesReq`：harness → `MemoryTool` 的整局单步记忆检索请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToMemoryToolQueryActMemoriesReq(BaseModel):
    """**取这一局的单步记忆**，可再按 task 筛（筛选放在查询条件里，不由调用方查完再筛）。"""

    episode_id: str = Field(description="这一局的标识")
    task_id: str | None = Field(default=None, description="只取这个 task 的；None = 整局")
