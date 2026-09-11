"""`FromHarnessToBrainToolChooseOnceResp`：harness → `BrainTool` 的决策响应。

字段同 `ChooseOnceResp`（`BrainTool` → `Brain` 的原生契约）——两套契约
独立维护，互转由 `BrainTool.choose_once()` 显式完成。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.brain.interface import ActionFromBrain
from pokemon_agent.providers.interface import ModelCall


class FromHarnessToBrainToolChooseOnceResp(BaseModel):
    """`BrainTool.choose_once()` 交回给 harness 的决策结果，字段同
    `ChooseOnceResp`（今天原样转发，未来 `BrainTool` 可以在这里做裁剪）。
    """

    action: ActionFromBrain = Field(description="这次尝试解析出的合法动作")
    calls: list[ModelCall] = Field(min_length=1, max_length=1, description="这次尝试自己的账")
    recalled: list[str] = Field(default_factory=list, description="取回了哪几条情景记忆")
