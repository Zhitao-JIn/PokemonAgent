"""`FromHarnessToBrainToolPlanOnceResp`：`BrainTool` → harness 的 run 级规划响应。

**`calls` 是整条重试链的账**，同 `FromHarnessToBrainToolChooseOnceResp`。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain.interface import RunPlan

from .ModelCall import ModelCall


class FromHarnessToBrainToolPlanOnceResp(BaseModel):
    """`BrainTool.plan()` 交回给 harness 的规划结果。

    **拿不到结果时抛 `MaxRetriesExceeded`**（整条账在异常里）。
    """

    plan: RunPlan = Field(description="这次尝试解析出的计划")
    calls: list[ModelCall] = Field(
        min_length=1, description="整条重试链的账，按尝试顺序，最后一个是成功那次"
    )
