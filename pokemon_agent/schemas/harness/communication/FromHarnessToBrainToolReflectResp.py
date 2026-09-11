"""`FromHarnessToBrainToolReflectResp`：harness → `BrainTool` 的反思响应。

字段同 `ReflectResp`（`BrainTool` → `Brain` 的原生契约）——两套契约
独立维护，互转由 `BrainTool.reflect()` 显式完成。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.memory import StepMemory


class FromHarnessToBrainToolReflectResp(BaseModel):
    """`BrainTool.reflect()` 交回给 harness 的反思结果。"""

    entry: StepMemory = Field(description="整理好的一条情景记忆")
