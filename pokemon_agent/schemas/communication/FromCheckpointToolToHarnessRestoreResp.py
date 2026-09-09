"""checkpoint 恢复响应：checkpoint tool → harness。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FromCheckpointToolToHarnessRestoreResp(BaseModel):
    """一份已通过签名校验的 checkpoint：恢复管线据此重建状态续跑。

    `state_dump`（EpisodeRunState）与 `run_state_dump`（RunState）来自同一份
    落盘 json——两层状态天然一致，不存在"两份数据要不要对得上"的问题
    （见 `FromHarnessToCheckpointToolSaveReq` docstring）。
    """

    run_id: str = Field(description="签名三元组之一")
    episode_id: str = Field(description="签名三元组之一")
    step: int = Field(description="签名三元组之一")
    state_dump: dict[str, Any] = Field(description="EpisodeRunState 的 model_dump")
    run_state_dump: dict[str, Any] = Field(description="这一步所属局对应的 RunState 的 model_dump")
    last_event_id: int = Field(description="trace 游标：恢复后续写从它 +1 开始")
    emulator_state: bytes = Field(description="模拟器世界快照")
    saved_at: str = Field(default="", description="ISO 保存时间（审计用，恢复逻辑不依赖）")
