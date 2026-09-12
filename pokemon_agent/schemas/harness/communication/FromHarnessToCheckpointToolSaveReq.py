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

    `frame_event_ids`/`pending_frames` 是本局的**帧账**两张表（v6 新增）：前者把
    步号对到"承载这一帧那条事件"的 event_id（截图文件名就是它），后者装"还没挂上
    任何事件的那一帧"的 base64 PNG（只有第 0 步那份存档可能非空）。两者都是
    `EpisodeHarness` 的内存态，**不随存档走就等于恢复后丢图**——链首 `OBSERVE`
    与第一个 store 步的 `before_frame` 都会是空的（截图明明在磁盘上，缺的只是
    "哪条事件承载这一步这一帧"这张对账）。
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
    frame_event_ids: dict[int, int] = Field(
        default_factory=dict,
        description="本局帧账之一：步号 → 承载该帧那条事件的 event_id（截图文件名）",
    )
    pending_frames: dict[int, str] = Field(
        default_factory=dict,
        description="本局帧账之二：步号 → 尚未挂上事件的帧的 base64 PNG（通常为空）",
    )
