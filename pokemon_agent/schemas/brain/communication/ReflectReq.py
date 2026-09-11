"""`Brain.reflect()` 的请求协议：`ReflectReq`。

`reflect()` 本版不调模型（见 `Brain.reflect()` 文档），所以没有对应的
`Resp`——它直接返回 `StepMemory`，无需另外包一层。"""

from __future__ import annotations

from pydantic import BaseModel

from pokemon_agent.brain.interface import ActionFromBrain
from pokemon_agent.world import Observation


class ReflectReq(BaseModel):
    """**递给 `reflect()` 的请求**：这一步的前后两帧观测 + 这次的动作。

    before：执行前的观测。
    action：这一步的动作。
    after：执行后的观测。
    """

    before: Observation
    action: ActionFromBrain
    after: Observation
