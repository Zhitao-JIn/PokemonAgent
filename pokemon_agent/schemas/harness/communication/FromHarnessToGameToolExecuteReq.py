"""`FromHarnessToGameToolExecuteReq`：harness → `GameTool` 的动作执行请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain.interface import ActionFromBrain
from pokemon_agent.world import Observation


class FromHarnessToGameToolExecuteReq(BaseModel):
    """**要执行的动作 + 它所依据的那一帧观测**。

    observation 一起带上是前置检查要用的：门面会断言这个动作确实来自
    这一帧算出的动作空间。
    """

    action: ActionFromBrain = Field(description="大脑选出的动作")
    observation: Observation = Field(description="这个动作所依据的观测")
