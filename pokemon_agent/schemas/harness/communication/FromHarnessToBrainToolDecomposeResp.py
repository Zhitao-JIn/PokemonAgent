"""episode 级拆解的响应信封。拿不到结果时抛 `MaxRetriesExceeded`（整条账在异常里）。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain.interface import Decomposition

from .ModelCall import ModelCall


class FromHarnessToBrainToolDecomposeResp(BaseModel):
    """一版任务链 + 整条重试链的账。"""

    decomposition: Decomposition = Field(description="解析出的任务链（task_id 由 harness 编）")
    calls: list[ModelCall] = Field(min_length=1, description="整条重试链的账，最后一个是成功那次")
