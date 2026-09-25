"""`FromHarnessToGameToolLoadStateReq`：harness → `GameTool` 的"从文件读回模拟器完整状态"请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToGameToolLoadStateReq(BaseModel):
    """**读哪一份**：由 `save_state` 写出的存档文件。"""

    path: str = Field(min_length=1, description="存档文件路径")
