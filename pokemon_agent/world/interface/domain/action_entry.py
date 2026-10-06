"""能力掩码里的**一个条目**：原子键与脚本在同一命名空间里。

键和脚本混在一张表里：它们都是"此刻可以调用的一个动作"，由模型同权选择；
一张掩码只有一次选择——名字 ∈ 掩码且 enabled。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .script_param import ScriptParam


class ActionEntry(BaseModel):
    """一个可选动作（键 / 脚本）。

    `kind` 只决定**载荷差异**（脚本有参数与说明，键只有一个名字），
    不决定选择方式——选择面是 `ActionSpace.mask` 那个扁平命名空间。
    """

    kind: Literal["key", "script"] = Field(description="动作归属；选择时不区分")
    name: str = Field(min_length=1, description="动作名（掩码的键）")
    params: list[ScriptParam] = Field(default_factory=list, description="参数签名；原子键为空")
    description: str = Field(default="", description="给模型读的说明（做什么、什么时候用）")

    def signature(self) -> str:
        """`buy_item(item: str, count: int)` 这种写法；无参动作就是名字本身。"""
        if not self.params:
            return self.name
        parts = [
            f"{p.name}: {p.type}" + ("" if p.default is None else f" = {p.default!r}")
            for p in self.params
        ]
        return f"{self.name}({', '.join(parts)})"


__all__ = ["ActionEntry"]
