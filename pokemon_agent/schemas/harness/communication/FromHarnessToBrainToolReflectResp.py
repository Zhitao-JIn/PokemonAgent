"""`FromHarnessToBrainToolReflectResp`：`BrainTool` → harness 的反思响应。

`entry` 是 `BrainTool` 直接用结构化观测（剪掉存储盲区）+ 它自己盖的坐标组装出的
**存储形状**（`ActMemory`）——组装在 tool 层，brain 与 memory 互不认识。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokemon_agent.schemas.memory import ActMemory


class FromHarnessToBrainToolReflectResp(BaseModel):
    """`Reflector.reflect()` 交回给 harness 的反思结果。"""

    entry: ActMemory = Field(description="组装好的一条情景记忆（坐标已盖章，尚未写库）")
