"""战斗双方状态框的结构化内存读数，含名字、等级、HP与异常状态。"""

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


__all__ = ["BattleStatus", "Combatant"]
