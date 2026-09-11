"""`FromHarnessToGameToolPerceiveOnceResp`：harness → `GameTool` 的单次感知响应。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.world import Observation


class FromHarnessToGameToolPerceiveOnceResp(BaseModel):
    """**一次感知的全部产物**：观测 + 这次调用产生的模型调用记录 + 原始帧。

    字段直接摊平自 world 自己的 `Perceived`（`tools/game_tools.py` 拆开转手）——
    这里不再嵌套一层 `PerceiveOnceResp`，那个信封已经随着"world 不依赖 schemas"
    这条原则撤销了。
    """

    observation: Observation = Field(description="这一帧的观测")
    calls: list[dict[str, str]] = Field(
        default_factory=list, description="这次调用产生的每一条模型调用记录"
    )
    frame_png: str = Field(description="这一次感知实际截下来、喂给视觉模型的原始 PNG（base64）")
