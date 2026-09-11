"""`FromHarnessToGameToolSaveStateBytesResp`：harness → `GameTool` 的世界快照响应。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToGameToolSaveStateBytesResp(BaseModel):
    """**模拟器世界快照字节**：唯一不可从事件重建的东西，checkpoint 靠它回档。"""

    emulator_state: bytes = Field(description="模拟器世界快照字节")
