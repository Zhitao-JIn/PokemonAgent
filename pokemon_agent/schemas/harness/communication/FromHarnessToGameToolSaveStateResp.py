"""`FromHarnessToGameToolSaveStateResp`：`GameTool` → harness 的存档结果。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToGameToolSaveStateResp(BaseModel):
    """**存下了什么**：落盘路径与字节数（清单与保真核对用）。"""

    path: str = Field(description="实际写入的文件路径")
    size: int = Field(gt=0, description="存档字节数")
