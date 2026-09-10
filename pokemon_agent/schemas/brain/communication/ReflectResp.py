"""BrainTool → Brain 的 reflect 交互：反思响应。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.memory import StepMemory


class ReflectResp(BaseModel):
    """一条整理好的经验（**看到什么 → 为什么 → 做了什么 → 变成什么**）。

    `episode_id` 由 Harness 盖章——大脑不知道自己在哪一局，恒为空串。
    """

    entry: StepMemory = Field(description="整理出的单步记忆条目（尚未写库）")
