"""`FromHarnessToBrainToolJudgeResp`：harness → `BrainTool` 的判定响应。

字段同 `FromBrainToolToBrainJudgeResp`（`BrainTool` → `Brain` 的原生契约）——两套契约
独立维护，互转由 `BrainTool.judge()` 显式完成。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.domain import ModelCall


class FromHarnessToBrainToolJudgeResp(BaseModel):
    """`BrainTool.judge()` 交回给 harness 的判定结果，字段同 `FromBrainToolToBrainJudgeResp`。
    跟 `Brain.judge()` 一样，**永远不抛异常**——渲染失败等前置错误由调用方
    （harness）自己兜住，构造出降级的 resp。
    """

    done: bool = Field(description="任务达成了没有")
    why: str = Field(description="看到了什么证据（或为什么证据不足）")
    call: ModelCall = Field(default_factory=lambda: ModelCall(), description="这次判定的账")
