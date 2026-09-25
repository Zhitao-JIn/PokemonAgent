"""`FromHarnessToGameToolSaveStateReq`：harness → `GameTool` 的"把模拟器完整状态存到文件"请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToGameToolSaveStateReq(BaseModel):
    """**存到哪**：文件路径由 harness 给（存档目录布局归 checkpointer），写文件在 tool 层。"""

    path: str = Field(min_length=1, description="存档文件路径；父目录不存在时由 tool 层创建")
