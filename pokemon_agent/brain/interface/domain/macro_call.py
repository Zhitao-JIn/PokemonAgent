"""宏调用（`MacroCall`）及其签名（`MacroSignature`）：接管场合里大脑吐出的另一种动作。

签名只带解析要用的东西（宏名、参数名、类型、是否必填）；给模型读的说明由调用方拼进 prompt。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MacroArg(BaseModel):
    """宏签名里的一个参数。"""

    name: str = Field(min_length=1, description="参数名")
    type: Literal["str", "int"] = Field(description="参数类型")
    required: bool = Field(default=True, description="是否必填")


class MacroSignature(BaseModel):
    """一个可调用的宏：名字 + 参数表。"""

    name: str = Field(min_length=1, description="宏名")
    params: list[MacroArg] = Field(default_factory=list, description="参数，按调用顺序")


class MacroCall(BaseModel):
    """一次宏调用：宏名 + 参数（只保证名字在空间里、参数类型对，不做语义校验）。"""

    name: str = Field(min_length=1, description="宏名")
    args: dict[str, str | int] = Field(default_factory=dict, description="参数名 -> 值")

    def describe(self) -> str:
        """`buy(POKé BALL, 5)` 这种写法。"""
        return f"{self.name}({', '.join(str(v) for v in self.args.values())})"


__all__ = ["MacroArg", "MacroCall", "MacroSignature"]
