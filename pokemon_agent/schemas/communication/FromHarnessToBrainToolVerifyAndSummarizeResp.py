"""`FromHarnessToBrainToolVerifyAndSummarizeResp`：harness → `BrainTool` 的校验+蒸馏响应。

字段同 `FromBrainToolToBrainVerifyAndSummarizeResp`（`BrainTool` → `Brain` 的原生契约）——两套契约
独立维护，互转由 `BrainTool.verify_and_summarize()` 显式完成。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.datastore import EpisodeMemory
from pokemon_agent.schemas.domain import ModelCall

from .FromBrainToLlmEpisodeSummaryResp import FromBrainToLlmEpisodeSummaryResp
from .step_verify import StepVerifyVerdict


class FromHarnessToBrainToolVerifyAndSummarizeResp(BaseModel):
    """`BrainTool.verify_and_summarize()` 交回给 harness 的结果，字段同
    `FromBrainToolToBrainVerifyAndSummarizeResp`。**永远不抛异常**，
    同 `Brain.verify_and_summarize()`。
    """

    verdicts: list[StepVerifyVerdict]
    summary: FromBrainToLlmEpisodeSummaryResp | None = None
    episode_memory: EpisodeMemory | None = None
    call: ModelCall = Field(default_factory=ModelCall)
    why: str = ""
