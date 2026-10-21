"""独立的原始观测视图契约。"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from .records import ActRecord


class ShopItem(BaseModel):
    name: str
    price: int = Field(ge=0)


class BagEntry(BaseModel):
    name: str
    quantity: int = Field(ge=0)


class ShopItemsView(BaseModel):
    kind: Literal["shop_items"] = "shop_items"
    items: list[ShopItem] = Field(default_factory=list)
    money: int = Field(ge=0)
    bag: list[BagEntry] = Field(default_factory=list)


class NamingView(BaseModel):
    kind: Literal["naming"] = "naming"
    target: str = Field()
    typed: str = Field(default="")


class MoveEntry(BaseModel):
    name: str
    pp: int = Field(ge=0)


class MonEntry(BaseModel):
    name: str = Field()
    level: int = Field(ge=0)
    hp: int = Field(ge=0)
    max_hp: int = Field(ge=0)
    status: str = Field(default="ok")
    active: bool = Field(default=False)
    moves: list[MoveEntry] = Field(default_factory=list)


class BattleMenuView(BaseModel):
    kind: Literal["battle_menu"] = "battle_menu"
    mine: MonEntry = Field()
    foe: MonEntry = Field()
    trainer: bool = Field(default=False)
    party: list[MonEntry] = Field(default_factory=list)
    bag: list[BagEntry] = Field(default_factory=list)


class BattleSwitchView(BaseModel):
    kind: Literal["battle_switch"] = "battle_switch"
    party: list[MonEntry] = Field(default_factory=list)


class BagView(BaseModel):
    kind: Literal["bag"] = "bag"
    bag: list[BagEntry] = Field(default_factory=list)
    party: list[MonEntry] = Field(default_factory=list)


class PartyView(BaseModel):
    kind: Literal["party"] = "party"
    party: list[MonEntry] = Field(default_factory=list)


class BoxEntry(BaseModel):
    name: str
    level: int = Field(ge=0)


class PcView(BaseModel):
    kind: Literal["pc"] = "pc"
    items: list[BagEntry] = Field(default_factory=list)
    bag: list[BagEntry] = Field(default_factory=list)
    box: list[BoxEntry] = Field(default_factory=list)
    box_number: int = Field(ge=1)
    party: list[MonEntry] = Field(default_factory=list)


class LearnMoveView(BaseModel):
    kind: Literal["learn_move"] = "learn_move"
    pokemon: str = Field()
    new_move: str = Field()
    moves: list[MoveEntry] = Field(default_factory=list)


TakeoverView = Annotated[
    ShopItemsView
    | NamingView
    | BattleMenuView
    | BattleSwitchView
    | BagView
    | PartyView
    | PcView
    | LearnMoveView,
    Field(discriminator="kind"),
]


class ObservationRecord(ActRecord.Observation):
    takeover: TakeoverView | None = None
    menu_decode_complete: bool | None = None
    covered_by_script: bool = False
    selected_map_location: str | None = None
    observation_notes: list[str] = Field(default_factory=list)
