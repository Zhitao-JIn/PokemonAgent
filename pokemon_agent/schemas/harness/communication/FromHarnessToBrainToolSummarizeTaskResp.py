"""`FromHarnessToBrainToolSummarizeTaskResp`：task 蒸馏的响应。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain.interface.domain import EpisodeSummary
from pokemon_agent.schemas.memory import TaskMemory

from .ModelCall import ModelCall


class FromHarnessToBrainToolSummarizeTaskResp(BaseModel):
    """蒸馏结果 + 组装好的存储形状 + 这次调用的账。"""

    summary: EpisodeSummary = Field(description="brain 的蒸馏产物（EpisodeSummary 方言）")
    memory: TaskMemory = Field(description="已组装好的存储形状（来源章已盖）")
    calls: list[ModelCall] = Field(description="这次调用的账（恰好一条）")
