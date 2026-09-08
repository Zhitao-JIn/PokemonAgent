"""`FromHarnessToBrainToolVerifyAndSummarizeReq`：harness → `BrainTool` 的校验+蒸馏请求。

字段同 `FromBrainToolToBrainVerifyAndSummarizeReq`（`BrainTool` → `Brain` 的原生契约）——两套契约
独立维护，互转由 `BrainTool.verify_and_summarize()` 显式完成。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.datastore import StepMemory


class FromHarnessToBrainToolVerifyAndSummarizeReq(BaseModel):
    """harness 侧组装、交给 `BrainTool` 的校验+蒸馏请求，字段同
    `FromBrainToolToBrainVerifyAndSummarizeReq`。"""

    goal: str
    entries: list[StepMemory]
    knowledge: str = ""
    images: list[str] = Field(default_factory=list)
    prompt: str = ""
    episode_id: str = ""
    run_id: str = ""
    success: bool
    steps: int = Field(ge=0)
    max_steps: int = Field(ge=1)
