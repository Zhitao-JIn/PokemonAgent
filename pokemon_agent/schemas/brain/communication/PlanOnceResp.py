"""`BrainTool` → `Brain` 这一跳的run 级规划响应协议：
`PlanOnceResp`。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain.interface import RunPlan
from pokemon_agent.providers.interface import ModelCall


class PlanOnceResp(BaseModel):
    """**`Brain.plan_once()` 一次尝试成功时的全部产物**：解析出的计划 + 这次的账。

    只在成功路径上用——失败（解析不出 `RunPlan`）时 `plan_once()` 抛
    `PlanAttemptFailed`（附这次的账），不走这个 resp；`calls` 恰好一条
    （这次尝试自己的账），多次尝试的累积在 Harness 那层的
    `run/plan.py::ask_planner_with_retry` 做，不在这里滚存。
    """

    plan: RunPlan = Field(description="这次尝试解析出的计划")
    calls: list[ModelCall] = Field(
        min_length=1, max_length=1, description="这次尝试自己的账，恰好一条"
    )
