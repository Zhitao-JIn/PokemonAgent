"""`FromHarnessToBrainToolReflectReq`：harness → `BrainTool` 的反思请求。

**harness 交完整观测，`BrainTool` 负责渲染 + 剪裁 + 盖章**：
- 渲染成文本（`before`/`after`）
- 剪掉不该进经验的字段（用 memory 的 `SNAPSHOT_BLIND`）
- 盖坐标（`episode_id`/`step`）

这三件都是"存储策略"，不是大脑的事——大脑只把四样东西装成 `Reflection`。
"""

from __future__ import annotations

from pydantic import BaseModel

from pokemon_agent.brain.interface import Action
from pokemon_agent.world import Observation


class FromHarnessToBrainToolReflectReq(BaseModel):
    """harness 侧组装、交给 `BrainTool` 的反思请求。

    before/action/after：这一步的前后两帧观测与这次的动作。
    episode_id/step：这一条记忆的坐标——**由 harness 给，不由大脑猜**。
        大脑不知道自己在哪一局、第几步。
    """

    before: Observation
    action: Action
    after: Observation
    episode_id: str = ""
    step: int = 0
