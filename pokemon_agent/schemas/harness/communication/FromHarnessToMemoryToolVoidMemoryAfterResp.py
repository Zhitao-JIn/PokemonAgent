"""`FromHarnessToMemoryToolVoidMemoryAfterResp`：harness → `MemoryTool` 的记忆截断响应。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToMemoryToolVoidMemoryAfterResp(BaseModel):
    """**各类被截掉的条数**（键 = 记忆种类）。"""

    removed: dict[str, int] = Field(description="各类被截掉的条数")
