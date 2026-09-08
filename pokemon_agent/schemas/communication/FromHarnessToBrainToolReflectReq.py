"""`FromHarnessToBrainToolReflectReq`：harness → `BrainTool` 的反思请求。

字段同 `FromBrainToolToBrainReflectReq`（`BrainTool` → `Brain` 的原生契约）——两套契约
独立维护，互转由 `BrainTool.reflect()` 显式完成。
"""

from __future__ import annotations

from pydantic import BaseModel

from pokemon_agent.schemas.domain import ActionFromBrain, ObservationFromWorld


class FromHarnessToBrainToolReflectReq(BaseModel):
    """harness 侧组装、交给 `BrainTool` 的反思请求，字段同 `FromBrainToolToBrainReflectReq`。"""

    before: ObservationFromWorld
    action: ActionFromBrain
    after: ObservationFromWorld
