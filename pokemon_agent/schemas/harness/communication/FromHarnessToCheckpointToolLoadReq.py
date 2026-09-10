"""harness → checkpoint tool 的 load 交互：恢复锚点定位请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToCheckpointToolLoadReq(BaseModel):
    """按三元组定位一份 checkpoint（恢复管线的锚点查找；找不到返回 None）。"""

    run_id: str = Field(description="签名三元组之一")
    episode_id: str = Field(description="签名三元组之一")
    step: int = Field(description="签名三元组之一")
