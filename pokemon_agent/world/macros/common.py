"""各场合宏共用的读数与操作：队伍、背包、道具分类，选项光标、列表光标、数量框、YES/NO。

地址按 `pret/pokered` 链接符号表：队伍 `wPartyMon1` 0xD16B 起每只 44 字节
（HP +1、状态 +4、招式 +8、PP +0x1D、等级 +0x21、最大 HP +0x22），
昵称 `wPartyMonNicks` 0xD2B5 起每个 11 字节；列表光标 `wCurrentMenuItem` 0xCC26 +
`wListScrollOffset` 0xCC36，数量 `wItemQuantity` 0xCF96。
"""

from __future__ import annotations

from ..battle_status import status_abbr, u16
from ..interface import BagEntry, MacroReason, Memory, MonEntry, MoveEntry, ScreenText
from ..items import item_id, item_name
from ..moves import fold, move_name
from ..ram import NAME_END, NAME_LENGTH
from ..readout import read_bag
from ..screen_text import CHARMAP
from .engine import Abort, MacroRun

W_CURRENT_MENU_ITEM = 0xCC26
W_LIST_SCROLL_OFFSET = 0xCC36
W_ITEM_QUANTITY = 0xCF96
W_PARTY_COUNT = 0xD163
W_PARTY_MON1 = 0xD16B
PARTY_MON_SIZE = 44
PARTY_CAPACITY = 6
MON_HP, MON_STATUS, MON_MOVES, MON_PP, MON_LEVEL, MON_MAX_HP = 0x01, 0x04, 0x08, 0x1D, 0x21, 0x22
W_PARTY_MON_NICKS = 0xD2B5
PP_MASK = 0x3F
"""PP 字节的低 6 位是剩余 PP（高 2 位是 PP UP 次数）。"""
MAX_QUANTITY = 99

BALLS = frozenset({0x01, 0x02, 0x03, 0x04})
HP_ITEMS = frozenset({0x10, 0x11, 0x12, 0x13, 0x14})
"""FULL RESTORE / MAX / HYPER / SUPER POTION / POTION。"""
STATUS_ITEMS = {0x0B: "PSN", 0x0C: "BRN", 0x0D: "FRZ", 0x0E: "SLP", 0x0F: "PAR", 0x34: ""}
"""ANTIDOTE / BURN HEAL / ICE HEAL / AWAKENING / PARLYZ HEAL / FULL HEAL（空串 = 任何异常）。"""
REVIVES = frozenset({0x35, 0x36})
HEAL_ITEMS = HP_ITEMS | frozenset(STATUS_ITEMS) | REVIVES
"""要选对象、且能事先判断有没有效果的药。"""


# ---- 读内存 ----


def party(mem: Memory, active: int = -1) -> list[MonEntry]:
    """队伍，按队伍顺序；第 `active` 只标在场。"""
    mons: list[MonEntry] = []
    for i in range(min(mem[W_PARTY_COUNT], PARTY_CAPACITY)):
        base = W_PARTY_MON1 + i * PARTY_MON_SIZE
        mons.append(
            MonEntry(
                name=nick(mem, W_PARTY_MON_NICKS + i * NAME_LENGTH),
                level=mem[base + MON_LEVEL],
                hp=u16(mem, base + MON_HP),
                max_hp=u16(mem, base + MON_MAX_HP),
                status=status_abbr(mem[base + MON_STATUS]),
                active=i == active,
                moves=moves(mem, base + MON_MOVES, base + MON_PP),
            )
        )
    return mons


def moves(mem: Memory, ids: int, pp: int) -> list[MoveEntry]:
    """四个招式槽里有招的那几个，带剩余 PP。"""
    return [
        MoveEntry(name=move_name(mem[ids + i]), pp=mem[pp + i] & PP_MASK)
        for i in range(4)
        if mem[ids + i]
    ]


def nick(mem: Memory, addr: int) -> str:
    """定长名字缓冲 → 字符串，遇 `NAME_END` 截止。"""
    chars: list[str] = []
    for i in range(NAME_LENGTH):
        byte = mem[addr + i]
        if byte == NAME_END:
            break
        chars.append(CHARMAP.get(byte, ""))
    return "".join(chars)


def bag(mem: Memory) -> list[BagEntry]:
    return [BagEntry(name=item_name(b.item_id), quantity=b.quantity) for b in read_bag(mem)]


def bag_count(mem: Memory, item: int) -> int:
    return sum(b.quantity for b in read_bag(mem) if b.item_id == item)


def bag_index(mem: Memory, item: int) -> int:
    return [b.item_id for b in read_bag(mem)].index(item)


def find_mon(mons: list[MonEntry], name: str) -> int | None:
    """按昵称找一只；同名的先给没倒下、不在场的。"""
    hits = [i for i, m in enumerate(mons) if fold(m.name) == fold(name)]
    usable = [i for i in hits if mons[i].hp > 0 and not mons[i].active]
    return (usable or hits or [None])[0]


def unknown_mon(mons: list[MonEntry], name: str) -> tuple[MacroReason, str]:
    names = "、".join(m.name for m in mons)
    return MacroReason.UNKNOWN_POKEMON, f"队伍里没有 {name}（有：{names}）"


def check_target(
    mons: list[MonEntry], name: str, *, need_bench: bool
) -> tuple[MacroReason, str] | None:
    """换人 / 派出的前提：在队伍里、没倒下；`need_bench` 时还要不在场。"""
    index = find_mon(mons, name)
    if index is None:
        return unknown_mon(mons, name)
    if mons[index].hp == 0:
        return MacroReason.POKEMON_FAINTED, f"{mons[index].name} 已经倒下"
    if need_bench and mons[index].active:
        return MacroReason.ALREADY_ACTIVE, f"{mons[index].name} 已经在场"
    return None


def useless(item: int, mon: MonEntry) -> tuple[MacroReason, str] | None:
    """这件药用在这只身上会不会没有效果。"""
    if item in REVIVES:
        return None if mon.hp == 0 else (MacroReason.CANNOT_USE, f"{mon.name} 没有倒下")
    if mon.hp == 0:
        return MacroReason.POKEMON_FAINTED, f"{mon.name} 已经倒下"
    if item in HP_ITEMS and mon.hp == mon.max_hp and (item != 0x10 or mon.status == "ok"):
        return MacroReason.CANNOT_USE, f"{mon.name} HP 已满"
    cures = STATUS_ITEMS.get(item)
    if cures is not None and (mon.status == "ok" or (cures and mon.status != cures)):
        return MacroReason.CANNOT_USE, f"{mon.name} 没有这个异常状态（{mon.status}）"
    return None


# ---- 操作 ----


def cursor_index(text: ScreenText) -> int:
    """光标在屏上选项里的下标；不在为 −1。"""
    names = [fold(o) for o in text.options]
    return names.index(fold(text.cursor)) if fold(text.cursor) in names else -1


def choose(run: MacroRun, option: str) -> None:
    """在屏上这一列选项里把光标挪到 `option`（按名字比），按 A；没有这一项抛 `Abort`。"""
    text = run.screen()
    names = [fold(o) for o in text.options]
    if fold(option) not in names:
        raise Abort(MacroReason.UNEXPECTED_SCREEN, f"选项里没有 {option}（有：{text.options}）")
    run.move_to(lambda: cursor_index(run.screen()), names.index(fold(option)), what=f"→ {option}")
    run.press("a", expect=f"选 {option}")


def pick_row(run: MacroRun, index: int, name: str) -> None:
    """长列表（会滚动）光标挪到第 `index` 项，核光标文字是 `name`，按 A。"""
    run.move_to(
        lambda: run.mem[W_CURRENT_MENU_ITEM] + run.mem[W_LIST_SCROLL_OFFSET],
        index,
        what=f"列表光标（{name}）",
    )
    cursor = run.screen().cursor
    if fold(cursor) != fold(name) and item_id(cursor) != item_id(name):
        raise Abort(MacroReason.UNEXPECTED_SCREEN, f"光标在 {cursor!r}，不是 {name}")
    run.press("a", expect=f"选 {name}")


def pick_mon(run: MacroRun, index: int, name: str) -> None:
    """队伍列表光标挪到第 `index` 只，按 A。"""
    run.move_to(lambda: run.mem[W_CURRENT_MENU_ITEM], index, what=f"队伍光标（{name}）")
    run.press("a", expect=f"选 {name}")


def set_quantity(run: MacroRun, n: int) -> None:
    """数量框调到 `n`，按 A。"""
    run.wait_for(lambda t: t.quantity_box, expect="数量框出现")
    run.move_to(lambda: run.mem[W_ITEM_QUANTITY], n, what="数量", increase="up")
    run.press("a", expect=f"数量 {n}")


def answer_yes(run: MacroRun, expect: str) -> None:
    """等 YES / NO 出现（途中的话替它推），选 YES。"""
    text = run.wait_for(
        lambda t: t.options == ["YES", "NO"], expect=expect, advance=lambda t: not t.has_cursor
    )
    if text.cursor != "YES":
        run.press("up", expect="光标到 YES", ok=lambda t: t.cursor == "YES")
    run.press("a", expect="选 YES")


def answer(run: MacroRun, choice: str) -> None:
    """当前就是 YES / NO：选 `choice`。"""
    if run.screen().cursor != choice:
        run.press("down" if choice == "NO" else "up", expect=f"光标到 {choice}")
    run.press("a", expect=f"选 {choice}")


__all__ = [
    "BALLS",
    "HEAL_ITEMS",
    "HP_ITEMS",
    "MAX_QUANTITY",
    "REVIVES",
    "STATUS_ITEMS",
    "answer",
    "answer_yes",
    "bag",
    "bag_count",
    "bag_index",
    "check_target",
    "choose",
    "cursor_index",
    "find_mon",
    "moves",
    "nick",
    "party",
    "pick_mon",
    "pick_row",
    "set_quantity",
    "unknown_mon",
    "useless",
]
