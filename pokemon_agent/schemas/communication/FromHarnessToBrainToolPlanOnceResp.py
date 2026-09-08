"""`FromHarnessToBrainToolPlanOnceResp`：harness → `BrainTool` 的run 级规划响应。

字段同 `FromBrainToolToBrainPlanOnceResp`（`BrainTool` → `Brain` 的原生契约）——两套契约
独立维护，互转由 `BrainTool.plan_once()` 显式完成。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.domain import ModelCall

from .run_plan import RunPlanResp


class FromHarnessToBrainToolPlanOnceResp(BaseModel):
    """`BrainTool.plan_once()` 交回给 harness 的规划结果，字段同
    `FromBrainToolToBrainPlanOnceResp`。"""

    plan: RunPlanResp = Field(description="这次尝试解析出的计划")
    calls: list[ModelCall] = Field(min_length=1, max_length=1, description="这次尝试自己的账")
