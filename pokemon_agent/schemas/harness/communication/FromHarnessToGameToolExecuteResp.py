"""`FromHarnessToGameToolExecuteResp`：`GameTool` → harness 的执行结果。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.world import MacroOutcome


class FromHarnessToGameToolExecuteResp(BaseModel):
    """一次 `execute` 的结果：宏动作带宏结果，按键动作为空。"""

    outcome: MacroOutcome | None = Field(
        default=None, description="宏的结果（成功 / 被拒 / 中途放弃 / 离开场合）；按键为 None"
    )
