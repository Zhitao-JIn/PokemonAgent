"""`FromHarnessToGameToolPerceiveOnceResp`：harness → `GameTool` 的单次感知响应。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.world import PerceiveOnceResp


class FromHarnessToGameToolPerceiveOnceResp(BaseModel):
    """**一次感知的全部产物**：装着 world 层自己的感知返回。"""

    perceived: PerceiveOnceResp = Field(description="world 层的单次感知返回")
