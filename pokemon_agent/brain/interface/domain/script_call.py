"""脚本调用（`ScriptCall`）及其签名（`ScriptSignature`）：大脑吐出的带参数的那种动作。

签名只带解析要用的东西（脚本名、参数名、类型、是否必填）；给模型读的说明由调用方拼进 prompt。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ScriptArg(BaseModel):
    """脚本签名里的一个参数。"""

    name: str = Field(min_length=1, description="参数名")
    type: Literal["str", "int"] = Field(description="参数类型")
    required: bool = Field(default=True, description="是否必填")


class ScriptSignature(BaseModel):
    """一个可调用的脚本：名字 + 参数表。"""

    name: str = Field(min_length=1, description="脚本名")
    params: list[ScriptArg] = Field(default_factory=list, description="参数，按调用顺序")


class ScriptCall(BaseModel):
    """一次脚本调用：脚本名 + 参数（只保证名字在空间里、参数类型对，不做语义校验）。"""

    name: str = Field(min_length=1, description="脚本名")
    args: dict[str, str | int] = Field(default_factory=dict, description="参数名 -> 值")


__all__ = ["ScriptArg", "ScriptCall", "ScriptSignature"]
