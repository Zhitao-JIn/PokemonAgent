"""`FromHarnessToGameToolEvolveReq`：harness → `GameTool` 的空转推进请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToGameToolEvolveReq(BaseModel):
    """**让世界空转若干帧**（等动画、等对话框弹出）。"""

    frames: int = Field(ge=0, description="空转帧数")
