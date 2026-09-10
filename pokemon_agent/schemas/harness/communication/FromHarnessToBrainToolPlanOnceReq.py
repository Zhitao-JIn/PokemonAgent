"""`FromHarnessToBrainToolPlanOnceReq`：harness → `BrainTool` 的run 级规划请求。

字段同 `PlanOnceReq`（`BrainTool` → `Brain` 的原生契约）——两套契约
独立维护，互转由 `BrainTool.plan_once()` 显式完成。
"""

from __future__ import annotations

from pydantic import BaseModel

from pokemon_agent.schemas.brain import TaskForBrain
from pokemon_agent.schemas.trace import TraceEvent


class FromHarnessToBrainToolPlanOnceReq(BaseModel):
    """harness 侧组装、交给 `BrainTool` 的规划请求，字段同 `PlanOnceReq`。"""

    run_id: str
    goals: list[TaskForBrain]
    events: list[TraceEvent]
    max_push: int
    prompt: str = ""
