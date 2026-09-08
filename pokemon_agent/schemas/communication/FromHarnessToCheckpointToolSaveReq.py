"""checkpoint 保存请求：harness → checkpoint tool。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class FromHarnessToCheckpointToolSaveReq(BaseModel):
    """一笔 checkpoint 的全部内容：签名三元组 + 状态快照 + trace 游标 + 世界快照。

    `state_dump` 是 `RunState`（level="run"）或 `EpisodeRunState`（level="step"）
    的 `model_dump()`——Pydantic 模型进不了 JSONL，落盘前由调用方摊平。
    `emulator_state` 是模拟器世界快照字节（`GameToolPort.save_state_bytes()`），
    level="run" 时为 None（run 级恢复用局起点存档，不背半途世界状态）。
    """

    run_id: str = Field(description="签名三元组之一；防跨 run 串档的显式字段")
    episode_id: str = Field(description="签名三元组之一")
    step: int = Field(ge=0, description="签名三元组之一；step 级=该步开局前，run 级=派发时（恒 0）")
    level: Literal["step", "run"] = Field(description="step=局内每步边界；run=dispatch 派发锚点")
    state_dump: dict[str, Any] = Field(description="RunState/EpisodeRunState 的 model_dump")
    last_event_id: int = Field(ge=-1, description="trace 游标：主前缀的最后一条 event_id")
    emulator_state: bytes | None = Field(default=None, description="模拟器世界快照；run 级为 None")
