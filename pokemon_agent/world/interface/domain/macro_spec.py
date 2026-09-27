"""`MacroSpec`：一个宏的签名——宏名、参数、给 LLM 读的说明。

world 定义，tools 转给 brain 与 prompt。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MacroParam(BaseModel):
    """宏的一个参数。"""

    name: str = Field(min_length=1, description="参数名")
    type: Literal["str", "int"] = Field(description="参数类型")
    description: str = Field(default="", description="给 LLM 读的说明")
    default: str | int | None = Field(default=None, description="缺省值；None = 必填")


class MacroSpec(BaseModel):
    """一个宏：接管场合里 JEV 能调用的一个动作。"""

    name: str = Field(min_length=1, description="宏名")
    params: list[MacroParam] = Field(default_factory=list, description="参数，按调用顺序")
    description: str = Field(default="", description="这个宏做什么、什么时候用")

    def signature(self) -> str:
        """`buy(item: str, quantity: int)` 这种写法。"""
        parts = [
            f"{p.name}: {p.type}" + ("" if p.default is None else f" = {p.default!r}")
            for p in self.params
        ]
        return f"{self.name}({', '.join(parts)})"


__all__ = ["MacroParam", "MacroSpec"]
