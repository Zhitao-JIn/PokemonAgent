"""`FromHarnessToMemoryToolRecallResp`：统一回忆的返回——混合条目，每条自带身份。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class FromHarnessToMemoryToolRecallItem(BaseModel):
    """一条回忆结果：kind 自带身份，消费方按需取 payload（各 kind 对应各自的 schema dump）。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["act", "task", "episode", "object", "knowledge"] = Field(
        description="这条来自哪个记忆族"
    )
    uuid: str = Field(description="记忆层生成的记录 uuid")
    score: float | None = Field(
        default=None, description="语义相关性分；hint 命中族（近因序）为 None"
    )
    content: str = Field(default="", description="渲染好的可读文本（感知束/模型直接可用）")
    payload: dict[str, Any] = Field(description="记录本体（各 kind schema 的 model_dump）")


class FromHarnessToMemoryToolRecallResp(BaseModel):
    """统一回忆的返回：融合排序后截断到 limit 的混合条目。"""

    items: list[FromHarnessToMemoryToolRecallItem] = Field(default_factory=list)
