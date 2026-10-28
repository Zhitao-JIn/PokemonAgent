"""`FromHarnessToGameToolExecuteResp`：`GameTool` → harness 的执行结果。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FromHarnessToGameToolExecuteResp(BaseModel):
    """一次 `execute` 的结果；只有脚本动作带终态报告。"""

    report: dict[str, Any] | None = Field(
        default=None,
        description="脚本的终态报告；按键为 None",
    )
