"""harness → checkpoint tool 的 void_after 交互：废弃归档请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToCheckpointToolVoidReq(BaseModel):
    """废弃恢复点之后的时间线（trace 截断、记忆截断、截图/存档归档）。

    前置条件：调用方已完成对账（快照签名/游标合法）——tool 不再自行校验。
    """

    run_id: str = Field(description="签名三元组之一")
    episode_id: str = Field(description="签名三元组之一（恢复目标局）")
    step: int = Field(description="签名三元组之一（恢复目标步）")
    cursor: int = Field(description="trace 游标：event_id > 它的事件全部废弃")
