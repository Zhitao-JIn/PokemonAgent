"""`FromHarnessToMemoryToolQueryTaskMemoriesReq`：task 记忆检索请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToMemoryToolQueryTaskMemoriesReq(BaseModel):
    """按 episode_id 等值筛——取这一局的全部 task 记忆，按 start_step 升序。"""

    episode_id: str = Field(description="这一局的标识")
