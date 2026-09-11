"""`FromHarnessToBrainToolJudgeReq`：harness → `BrainTool` 的判定请求。

字段同 `JudgeReq`（`BrainTool` → `Brain` 的原生契约）——两套契约
独立维护，互转由 `BrainTool.judge()` 显式完成。
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from pokemon_agent.brain.interface import GoalForBrain
from pokemon_agent.memory import StepMemory


class FromHarnessToBrainToolJudgeReq(BaseModel):
    """harness 侧组装、交给 `BrainTool` 的判定请求，字段同 `JudgeReq`。"""

    goal: GoalForBrain
    history: Sequence[StepMemory] = ()
    images: Sequence[bytes] = ()
    prompt: str = ""
