"""`FromHarnessToBrainToolChooseOnceReq`：harness → `BrainTool` 的决策请求。

字段同 `ChooseOnceReq`（`BrainTool` → `Brain` 的原生契约）——两套契约
独立维护，互转由 `BrainTool.choose_once()` 显式完成。
"""

from __future__ import annotations

from pydantic import BaseModel

from pokemon_agent.schemas.brain import GoalForBrain
from pokemon_agent.schemas.memory import StepMemory
from pokemon_agent.schemas.world import ActionSpaceForBrain, ObservationFromWorld


class FromHarnessToBrainToolChooseOnceReq(BaseModel):
    """harness 侧组装（`harness/brain_utils.py`，纯参数拼接）、交给 `BrainTool`
    的决策请求。字段含义同 `ChooseOnceReq`，见该文件的完整说明。
    """

    goals: list[GoalForBrain]
    obs: ObservationFromWorld
    space: ActionSpaceForBrain
    memories: list[StepMemory]
    knowledge: str = ""
    episode_memories: str = ""
    human_note: str = ""
    prompt: str = ""
