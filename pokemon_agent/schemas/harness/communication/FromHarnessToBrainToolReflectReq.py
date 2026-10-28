"""`FromHarnessToBrainToolReflectReq`：harness → `BrainTool` 的反思请求。

**harness 交完整观测，`BrainTool` 负责筛选 + 盖章**：
- 剪掉不该进经验的字段（用 memory 的 `SNAPSHOT_BLIND`）
- 盖坐标（`episode_id`/`step`）

这两件都是"存储策略"，不是大脑的事。`Reflector` 直接用结构化观测组装 `ActMemory`，
不调用大脑。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain.interface import Action
from pokemon_agent.schemas.memory import ActMemory
from pokemon_agent.world import RamReadout, TaskObservation


class FromHarnessToBrainToolReflectReq(BaseModel):
    """harness 侧组装、交给 `BrainTool` 的反思请求。

    before/action/after：这一步的前后两帧观测与这次的动作。
    episode_id/step：这一条记忆的坐标——**由 harness 给，不由大脑猜**。
        大脑不知道自己在哪一局、第几步。
    """

    before: TaskObservation
    action: Action
    after: TaskObservation
    episode_id: str = ""
    step: int = 0
    outcome: ActMemory.ScriptOutcome | None = None
    observations: list[ActMemory.Observation.StepObs] = Field(default_factory=list)
    before_ram: RamReadout | None = None
    after_ram: RamReadout | None = None
