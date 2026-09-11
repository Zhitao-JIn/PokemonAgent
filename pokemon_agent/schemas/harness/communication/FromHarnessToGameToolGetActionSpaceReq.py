"""`FromHarnessToGameToolGetActionSpaceReq`：harness → `GameTool` 的动作空间请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.world import Observation


class FromHarnessToGameToolGetActionSpaceReq(BaseModel):
    """**按这份观测算此刻的动作空间**：掩码只看 overlay，不看目标与历史。"""

    observation: Observation = Field(description="要算掩码的这一帧观测")
