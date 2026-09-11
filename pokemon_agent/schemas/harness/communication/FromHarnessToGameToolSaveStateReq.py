"""`FromHarnessToGameToolSaveStateReq`：harness → `GameTool` 的存档落盘请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToGameToolSaveStateReq(BaseModel):
    """**把世界快照写到指定路径**。"""

    path: str = Field(description="快照文件路径")
