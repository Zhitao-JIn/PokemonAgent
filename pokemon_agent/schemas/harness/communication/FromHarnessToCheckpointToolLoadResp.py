"""harness → checkpoint tool 的 load 交互：恢复响应。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FromHarnessToCheckpointToolLoadResp(BaseModel):
    """一份已通过签名校验的 checkpoint：恢复管线据此重建状态续跑。

    `state_dump`（EpisodeRunState）与 `run_state_dump`（RunState）来自同一份
    落盘 json——两层状态天然一致，不存在"两份数据要不要对得上"的问题
    （见 `FromHarnessToCheckpointToolSaveReq` docstring）。

    `frame_event_ids`/`pending_frames` 是本局帧账（v6）：`resume()` 拿它们回填
    内存里的两张表，恢复后第一条 `OBSERVE` 才带得上帧。**缺字段的老档一律当空表**
    ——那正是"这份存档没带帧账"（v6 之前写的档）的准确语义，不是错误。
    """

    run_id: str = Field(description="签名三元组之一")
    episode_id: str = Field(description="签名三元组之一")
    step: int = Field(description="签名三元组之一")
    state_dump: dict[str, Any] = Field(description="EpisodeRunState 的 model_dump")
    run_state_dump: dict[str, Any] = Field(description="这一步所属局对应的 RunState 的 model_dump")
    last_event_id: int = Field(description="trace 游标：恢复后续写从它 +1 开始")
    emulator_state: bytes = Field(description="模拟器世界快照")
    saved_at: str = Field(default="", description="ISO 保存时间（审计用，恢复逻辑不依赖）")
    frame_event_ids: dict[int, int] = Field(
        default_factory=dict,
        description="本局帧账之一：步号 → 承载该帧那条事件的 event_id（v6 前的档为空）",
    )
    pending_frames: dict[int, str] = Field(
        default_factory=dict,
        description="本局帧账之二：步号 → 未挂上事件的帧的 base64 PNG（v6 前的档为空）",
    )
