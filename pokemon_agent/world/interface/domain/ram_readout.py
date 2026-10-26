"""`RamReadout`：一帧的内存读数，先记入 trace（`sense_frame.content.ram`）。

run 判定可从本执行线账本读取最近至多五条作为直接证据；规划与动作输入不直接增加该字段。

它是测评机械判定读真值的唯一来源（`docs/eval/spec.md` W2）：战斗标志、屏幕解码是否覆盖、
这一帧文字字段来自哪边、菜单光标变量、金钱、背包、队伍、战斗双方状态框。
`decoded` 是屏幕解码出的文字，每帧都记（看档帧上与视觉给的并排），测评的机械判据只认它。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .battle_status import BattleStatus

TextSource = Literal["decode", "vlm"]
"""一帧 `Facts` 的对话 / 选项 / 光标来自哪边：屏幕解码（task 层）或视觉模型（episode 层）。"""


class MenuVars(BaseModel):
    """菜单光标的游戏变量。含义随菜单而变，只作旁证。"""

    current_item: int = Field(description="`wCurrentMenuItem`：光标在第几项（从 0 起）")
    max_item: int = Field(description="`wMaxMenuItem`：这个菜单的最大项号")
    top_x: int = Field(description="`wTopMenuItemX`：光标那一列在屏幕上的列号（2×2 菜单靠它分列）")


class BagItem(BaseModel):
    """背包里的一种物品。"""

    item_id: int
    quantity: int


class PartyMon(BaseModel):
    """队伍里的一只。"""

    species: int
    level: int
    hp: int
    max_hp: int
    status: str = Field(description="ok / SLP / PSN / BRN / FRZ / PAR")


class DecodedText(BaseModel):
    """屏幕解码出的文字。"""

    dialog_text: str
    options: list[str]
    cursor: str


class RamReadout(BaseModel):
    """一帧的内存读数。"""

    in_battle: bool
    covered: bool = Field(description="屏幕解码是否完整覆盖这一帧的选单（`ScreenText.covered`）")
    text_source: TextSource = Field(description="这一帧 `Facts` 里的文字字段实际来自哪边")
    menu: MenuVars
    money: int
    bag: list[BagItem]
    party: list[PartyMon]
    battle: BattleStatus | None = None
    decoded: DecodedText = Field(description="这一帧屏幕解码出的文字（两层都记）")


__all__ = ["BagItem", "DecodedText", "MenuVars", "PartyMon", "RamReadout", "TextSource"]
