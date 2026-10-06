"""能力掩码里的**一个条目**：原子键与宏（P4 起还有脚本）在同一命名空间里。

**为什么键和宏要混在一张表里**（2026-09-29 定案）：在 MCP 提供层面它们是
等价的——都是"此刻可以调用的一个动作"，由模型同权选择。分开成两张表
（`names` + `macros`）会让调用方必须先选类型再选动作，那是**两层决策**；
一张掩码只有一次选择：名字 ∈ 掩码且 enabled。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .macro_spec import MacroParam


class ActionEntry(BaseModel):
    """一个可选动作（键 / 宏 / 将来的脚本）。

    `kind` 只决定**载荷差异**（宏有参数与说明，键只有一个名字），
    不决定选择方式——选择面是 `ActionSpace.mask` 那个扁平命名空间。
    """

    kind: Literal["key", "macro", "script"] = Field(description="动作归属；选择时不区分")
    name: str = Field(min_length=1, description="动作名（掩码的键）")
    params: list[MacroParam] = Field(default_factory=list, description="参数签名；原子键为空")
    description: str = Field(default="", description="给模型读的说明（做什么、什么时候用）")

    def signature(self) -> str:
        """`buy(item: str, quantity: int)` 这种写法；无参动作就是名字本身。"""
        if not self.params:
            return self.name
        parts = [
            f"{p.name}: {p.type}" + ("" if p.default is None else f" = {p.default!r}")
            for p in self.params
        ]
        return f"{self.name}({', '.join(parts)})"


__all__ = ["ActionEntry"]
