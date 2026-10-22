"""仅开放脚本的场合的视图（`TakeoverView`）：按场合区分的判别联合，给 JEV 看本场合调脚本的依据。

观测里不给逐键信息（光标位置、翻页）——那是脚本执行器的事。
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ShopItem(BaseModel):
    """店里卖的一样东西。"""

    name: str
    price: int = Field(ge=0, description="单价")


class BagEntry(BaseModel):
    """背包里的一样东西。"""

    name: str
    quantity: int = Field(ge=0)


class ShopItemsView(BaseModel):
    """商店买卖：商品表、金钱、背包。"""

    kind: Literal["shop_items"] = "shop_items"
    items: list[ShopItem] = Field(default_factory=list, description="商品（名、单价）")
    money: int = Field(ge=0, description="当前金钱")
    bag: list[BagEntry] = Field(default_factory=list, description="背包（名、数量）")


class NamingView(BaseModel):
    """起名键盘：给谁起名、已输入的名字。"""

    kind: Literal["naming"] = "naming"
    target: str = Field(
        description="给谁起名：屏幕标题原样（YOUR NAME? / RIVAL's NAME? / NICKNAME?）"
    )
    typed: str = Field(default="", description="已输入的名字")


class MoveEntry(BaseModel):
    """一个招式与剩余 PP。"""

    name: str
    pp: int = Field(ge=0, description="剩余 PP")


class MonEntry(BaseModel):
    """队伍里的一只（或战斗中的一方）：昵称、等级、HP、状态、招式。"""

    name: str = Field(description="昵称（屏幕上显示的名字）")
    level: int = Field(ge=0)
    hp: int = Field(ge=0)
    max_hp: int = Field(ge=0)
    status: str = Field(default="ok", description="状态缩写：ok / PSN / BRN / FRZ / PAR / SLP")
    active: bool = Field(default=False, description="是不是正在场上的那只")
    moves: list[MoveEntry] = Field(default_factory=list, description="招式与剩余 PP；对手为空")


class BattleMenuView(BaseModel):
    """战斗选单：在场宝可梦与招式、对手、队伍、背包。"""

    kind: Literal["battle_menu"] = "battle_menu"
    mine: MonEntry = Field(description="我方在场的那只（带招式与 PP）")
    foe: MonEntry = Field(description="对手")
    trainer: bool = Field(default=False, description="训练家对战（不能逃、不能扔球）")
    party: list[MonEntry] = Field(default_factory=list, description="队伍，按队伍顺序")
    bag: list[BagEntry] = Field(default_factory=list, description="背包（名、数量）")


class BattleSwitchView(BaseModel):
    """战斗换人：队伍；主动换人与倒下换人使用同一形状。"""

    kind: Literal["battle_switch"] = "battle_switch"
    party: list[MonEntry] = Field(default_factory=list, description="队伍，按队伍顺序")


class BagView(BaseModel):
    """野外背包：背包、队伍（给药要选对象）。"""

    kind: Literal["bag"] = "bag"
    bag: list[BagEntry] = Field(default_factory=list, description="背包（名、数量）")
    party: list[MonEntry] = Field(default_factory=list, description="队伍，按队伍顺序")


class PartyView(BaseModel):
    """野外队伍列表：队伍与各自的招式。"""

    kind: Literal["party"] = "party"
    party: list[MonEntry] = Field(default_factory=list, description="队伍，按队伍顺序")


class BoxEntry(BaseModel):
    """PC 箱里的一只：昵称、等级。"""

    name: str
    level: int = Field(ge=0)


class PcView(BaseModel):
    """PC：PC 里的道具、背包、当前箱里的宝可梦、当前箱号、队伍。"""

    kind: Literal["pc"] = "pc"
    items: list[BagEntry] = Field(default_factory=list, description="存在 PC 里的道具")
    bag: list[BagEntry] = Field(default_factory=list, description="背包")
    box: list[BoxEntry] = Field(default_factory=list, description="当前箱里的宝可梦")
    box_number: int = Field(ge=1, description="当前箱号（1–12）")
    party: list[MonEntry] = Field(default_factory=list, description="队伍")


class LearnMoveView(BaseModel):
    """学新招要忘旧招：谁在学、想学的招、现有四招。"""

    kind: Literal["learn_move"] = "learn_move"
    pokemon: str = Field(description="正在学招的宝可梦（昵称）")
    new_move: str = Field(description="想学的招")
    moves: list[MoveEntry] = Field(default_factory=list, description="现有的招与剩余 PP")


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
"""仅开放脚本的场合的视图；还没有脚本的仅开放脚本的场合不给视图（None）。"""


__all__ = [
    "BagEntry",
    "BagView",
    "BoxEntry",
    "LearnMoveView",
    "PartyView",
    "PcView",
    "BattleMenuView",
    "BattleSwitchView",
    "MonEntry",
    "MoveEntry",
    "NamingView",
    "ShopItem",
    "ShopItemsView",
    "TakeoverView",
]
