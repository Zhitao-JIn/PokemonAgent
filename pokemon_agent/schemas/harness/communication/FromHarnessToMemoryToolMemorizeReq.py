"""`FromHarnessToMemoryToolMemorizeReq`：harness → `MemoryTool` 的统一记忆请求。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class FromHarnessToMemoryToolMemorizeRecord(BaseModel):
    """一条待落库的记忆：kind 判别落族，payload 为对应 schema 的 model_dump。

    种类由产生方天然决定（蒸馏产 summary、act 环产
    act 记忆）——调用方不猜种类，只报身份。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["act", "task", "episode", "knowledge", "run"] = Field(
        description="这条属于哪个记忆族"
    )
    payload: dict[str, Any] = Field(description="记录本体（对应 kind schema 的 model_dump）")


class FromHarnessToMemoryToolMemorizeReq(BaseModel):
    """**统一记忆口**：写侧一个口，records 按 kind 判别落族。"""

    records: list[FromHarnessToMemoryToolMemorizeRecord] = Field(default_factory=list)
