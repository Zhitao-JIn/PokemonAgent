"""`FromHarnessToGameToolGetActionSpaceResp`：harness → `GameTool` 的动作空间响应。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.world import ActionSpaceForBrain


class FromHarnessToGameToolGetActionSpaceResp(BaseModel):
    """**这一帧允许按下的动作**。"""

    action_space: ActionSpaceForBrain = Field(description="掩码后的动作空间")
