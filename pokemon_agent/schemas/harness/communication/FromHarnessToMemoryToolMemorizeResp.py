"""`FromHarnessToMemoryToolMemorizeResp`：统一记忆的返回——实际落库的条目。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FromHarnessToMemoryToolMemorizedRecord(BaseModel):
    """一条真落库的记忆（kind + uuid）。被判重跳过的不在其中。"""

    kind: str = Field(description="记忆族")
    uuid: str = Field(description="记忆层生成的记录 uuid；knowledge 判重跳过时不出现在 stored")


class FromHarnessToMemoryToolMemorizeResp(BaseModel):
    """统一记忆的返回：实际落库条目清单（是请求 records 的子序列）。"""

    stored: list[FromHarnessToMemoryToolMemorizedRecord] = Field(default_factory=list)
