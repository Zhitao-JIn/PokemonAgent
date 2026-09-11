"""`FromHarnessToGameToolLoadStateBytesReq`：harness → `GameTool` 的快照回载请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToGameToolLoadStateBytesReq(BaseModel):
    """**要回载的世界快照字节**。"""

    emulator_state: bytes = Field(description="模拟器世界快照字节")
