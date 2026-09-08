"""checkpoint 恢复响应：checkpoint tool → harness。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FromCheckpointToolToHarnessRestoreResp(BaseModel):
    """一份已通过签名校验的 checkpoint：恢复管线据此重建状态续跑。"""

    run_id: str = Field(description="签名三元组之一")
    episode_id: str = Field(description="签名三元组之一")
    step: int = Field(description="签名三元组之一")
    level: str = Field(description='"step" 或 "run"')
    state_dump: dict[str, Any] = Field(
        description="RunState/EpisodeRunState 的 model_dump（按 level）"
    )
    last_event_id: int = Field(description="trace 游标：恢复后续写从它 +1 开始")
    emulator_state: bytes | None = Field(default=None, description="模拟器世界快照；run 级为 None")
    saved_at: str = Field(default="", description="ISO 保存时间（审计用，恢复逻辑不依赖）")
