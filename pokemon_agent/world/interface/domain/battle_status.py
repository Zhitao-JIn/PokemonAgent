"""`BattleStatus`：战斗中双方状态框的内存读数——`battle_status.read_battle_status` 的产出 schema。

双方的名字、等级、HP、状态异常都是游戏变量，直接从内存读，不经视觉模型。
`facts_fields()` 把它压成 `Facts` 动态字段（`my_*` / `foe_*`）那一份字符串形状。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Combatant(BaseModel):
    """战斗中一方的状态框。"""

    name: str = Field(description="昵称（我方）或种类名（野生对手），按字表解码")
    level: int = Field(ge=0)
    hp: int = Field(ge=0)
    max_hp: int = Field(ge=0)
    status: str = Field(description="状态异常缩写：ok / SLP / PSN / BRN / FRZ / PAR")


class BattleStatus(BaseModel):
    """这一帧战斗双方的状态框；不在战斗时不产出这个对象。"""

    mine: Combatant
    foe: Combatant

    def facts_fields(self) -> dict[str, str]:
        """压成 `Facts` 动态字段：`my_hp` / `foe_hp` 是 `当前/最大`，其余照值转字符串。"""
        out: dict[str, str] = {}
        for prefix, side in (("my", self.mine), ("foe", self.foe)):
            out[f"{prefix}_name"] = side.name
            out[f"{prefix}_level"] = str(side.level)
            out[f"{prefix}_hp"] = f"{side.hp}/{side.max_hp}"
            out[f"{prefix}_status"] = side.status
        return out


__all__ = ["BattleStatus", "Combatant"]
