"""一帧的内存读数（`RamReadout`）：菜单光标变量、金钱、背包、队伍、战斗状态框，加上文字来源的标注。

全部是游戏变量，地址在 `ram.py`。只进 trace，不进 agent 输入（`docs/eval/spec.md` W2）。
"""

from __future__ import annotations

from .battle_status import read_battle_status, status_abbr, u16
from .interface import (
    BagItem,
    DecodedText,
    Memory,
    MenuVars,
    PartyMon,
    RamReadout,
    ScreenText,
    TextSource,
)
from .ram import (
    BAG_CAPACITY,
    LIST_END,
    PARTY_CAPACITY,
    PARTY_MON_SIZE,
    W_BAG_ITEMS,
    W_CURRENT_MENU_ITEM,
    W_MAX_MENU_ITEM,
    W_NUM_BAG_ITEMS,
    W_PARTY_COUNT,
    W_PARTY_MON1_HP,
    W_PARTY_SPECIES,
    W_PLAYER_MONEY,
    W_TOP_MENU_ITEM_X,
)


def read_readout(
    mem: Memory,
    text: ScreenText,
    *,
    text_source: TextSource,
) -> RamReadout:
    """读这一帧的内存读数；屏幕解码的文字每帧都记（`decoded`），测评只认它。"""
    decoded = DecodedText(dialog_text=text.dialog_text, options=text.options, cursor=text.cursor)
    return RamReadout(
        in_battle=text.in_battle,
        covered=text.covered,
        text_source=text_source,
        menu=MenuVars(
            current_item=mem[W_CURRENT_MENU_ITEM],
            max_item=mem[W_MAX_MENU_ITEM],
            top_x=mem[W_TOP_MENU_ITEM_X],
        ),
        money=read_money(mem),
        bag=read_bag(mem),
        party=_party(mem),
        battle=read_battle_status(mem),
        decoded=decoded,
    )


def read_money(mem: Memory) -> int:
    """金钱：3 字节 BCD。"""
    total = 0
    for i in range(3):
        byte = mem[W_PLAYER_MONEY + i]
        total = total * 100 + (byte >> 4) * 10 + (byte & 0x0F)
    return total


def read_bag(mem: Memory) -> list[BagItem]:
    """背包：件数封顶 `BAG_CAPACITY`，遇 `LIST_END` 截止。"""
    items: list[BagItem] = []
    for i in range(min(mem[W_NUM_BAG_ITEMS], BAG_CAPACITY)):
        item_id = mem[W_BAG_ITEMS + 2 * i]
        if item_id == LIST_END:
            break
        items.append(BagItem(item_id=item_id, quantity=mem[W_BAG_ITEMS + 2 * i + 1]))
    return items


def _party(mem: Memory) -> list[PartyMon]:
    """队伍：只数 `wPartyCount` 只（封顶 `PARTY_CAPACITY`）。"""
    party: list[PartyMon] = []
    for i in range(min(mem[W_PARTY_COUNT], PARTY_CAPACITY)):
        base = W_PARTY_MON1_HP + i * PARTY_MON_SIZE
        party.append(
            PartyMon(
                species=mem[W_PARTY_SPECIES + i],
                level=mem[base + 0x20],
                hp=u16(mem, base),
                max_hp=u16(mem, base + 0x21),
                status=status_abbr(mem[base + 3]),
            )
        )
    return party


__all__ = ["read_bag", "read_money", "read_readout"]
