"""`FromHarnessToBrainToolPlanOnceReq`：harness → `BrainTool` 的run 级规划请求。

字段同 `FromBrainToolToBrainPlanOnceReq`（`BrainTool` → `Brain` 的原生契约）——两套契约
独立维护，互转由 `BrainTool.plan_once()` 显式完成。
"""

from __future__ import annotations

from pydantic import BaseModel

from pokemon_agent.schemas.datastore import TraceEvent
from pokemon_agent.schemas.domain import TaskForHarness


class FromHarnessToBrainToolPlanOnceReq(BaseModel):
    """harness 侧组装、交给 `BrainTool` 的规划请求，字段同 `FromBrainToolToBrainPlanOnceReq`。"""

    run_id: str
    goals: list[TaskForHarness]
    events: list[TraceEvent]
    max_push: int
    prompt: str = ""
