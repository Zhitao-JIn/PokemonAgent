"""`ScriptParam`：一条脚本的一个参数——参数名、类型、说明、缺省值。

world 定义，tools 转给 brain（解析用的签名）与 prompt（给模型读的签名）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ScriptParam(BaseModel):
    """脚本的一个参数。"""

    name: str = Field(min_length=1, description="参数名")
    type: Literal["str", "int"] = Field(description="参数类型")
    description: str = Field(default="", description="给 LLM 读的说明")
    default: str | int | None = Field(default=None, description="缺省值；None = 必填")


__all__ = ["ScriptParam"]
