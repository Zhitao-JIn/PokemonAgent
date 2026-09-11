"""checkpoint 保存请求：harness → checkpoint tool。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FromHarnessToCheckpointToolSaveReq(BaseModel):
    """一笔 checkpoint 的全部内容：签名三元组 + 两层状态快照 + trace 游标 + 世界快照。

    只有一种落盘形态（没有 run/step 两级之分）：每次 `save_checkpoint` 节点
    存档时，`EpisodeRunState`（`state_dump`）与当时的 `RunState`
    （`run_state_dump`）一起打包进同一份 json——`RunState` 在同一局内的每一步
    都相同（只有 `dispatch`/`reflect` 会改它，均在局间发生），这里只是纯透传，
    换来"resume 只需读一份文件就能同时重建两层状态"。两者都是 `model_dump()`
    ——Pydantic 模型进不了 JSONL，落盘前由调用方摊平。
    `emulator_state` 是模拟器世界快照字节（`GameToolPort.save_state_bytes()`）。
    """

    run_id: str = Field(description="签名三元组之一；防跨 run 串档的显式字段")
    episode_id: str = Field(description="签名三元组之一")
    step: int = Field(ge=0, description="签名三元组之一：该步开局前")
    state_dump: dict[str, Any] = Field(description="EpisodeRunState 的 model_dump")
    run_state_dump: dict[str, Any] = Field(
        description="这一步所属局对应的 RunState 的 model_dump（纯透传，episode 层不解读）"
    )
    last_event_id: int = Field(ge=-1, description="trace 游标：主前缀的最后一条 event_id")
    emulator_state: bytes = Field(description="模拟器世界快照")
